"""
Unit tests for TITAN FUSE Protocol v3.2.3.

Tests core functionality of all modules.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import unittest
from datetime import datetime


class TestAssessment(unittest.TestCase):
    """Tests for AssessmentScore module."""

    def test_signal_strength_enum(self):
        """Test SignalStrength enum values."""
        from src.state.assessment import SignalStrength
        self.assertEqual(SignalStrength.WEAK.value, 1)
        self.assertEqual(SignalStrength.MODERATE.value, 2)
        self.assertEqual(SignalStrength.STRONG.value, 3)

    def test_readiness_tier_enum(self):
        """Test ReadinessTier enum values."""
        from src.state.assessment import ReadinessTier
        self.assertEqual(ReadinessTier.PRODUCTION_READY.value, "PRODUCTION_READY")
        self.assertEqual(ReadinessTier.EXPERIMENTAL.value, "EXPERIMENTAL")
        self.assertEqual(ReadinessTier.REVIEW_REQUIRED.value, "REVIEW_REQUIRED")

    def test_assessment_score_calculate(self):
        """Test assessment score calculation."""
        from src.state.assessment import AssessmentScore, SignalStrength, ReadinessTier

        # High confidence, low volatility -> production ready
        score = AssessmentScore.calculate("low", 0.95)
        self.assertEqual(score.signal, SignalStrength.STRONG)
        self.assertEqual(score.readiness, ReadinessTier.PRODUCTION_READY)
        self.assertGreater(score.combined_score, 0.8)

        # Low confidence -> review required
        score = AssessmentScore.calculate("medium", 0.5)
        self.assertEqual(score.readiness, ReadinessTier.REVIEW_REQUIRED)

    def test_assessment_score_serialization(self):
        """Test to_dict and from_dict."""
        from src.state.assessment import AssessmentScore

        score = AssessmentScore.calculate("low", 0.9)
        data = score.to_dict()

        self.assertIn("signal", data)
        self.assertIn("readiness", data)
        self.assertIn("combined_score", data)

        restored = AssessmentScore.from_dict(data)
        self.assertEqual(restored.signal, score.signal)
        self.assertEqual(restored.readiness, score.readiness)


class TestStateManager(unittest.TestCase):
    """Tests for State Manager module."""

    def test_evidence_type_enum(self):
        """Test EvidenceType enum values."""
        from src.state.state_manager import EvidenceType
        self.assertEqual(EvidenceType.FACT.value, "FACT")
        self.assertEqual(EvidenceType.GAP.value, "GAP")

    def test_reasoning_step(self):
        """Test ReasoningStep creation and serialization."""
        from src.state.state_manager import ReasoningStep, EvidenceType

        step = ReasoningStep(
            content="Test reasoning",
            evidence_type=EvidenceType.FACT,
            confidence=0.9,
            source_ref="test.py:10"
        )

        data = step.to_dict()
        self.assertEqual(data["content"], "Test reasoning")
        self.assertEqual(data["evidence_type"], "FACT")

        restored = ReasoningStep.from_dict(data)
        self.assertEqual(restored.content, step.content)

    def test_budget_manager(self):
        """Test BudgetManager allocation."""
        from src.state.state_manager import BudgetManager

        bm = BudgetManager(max_tokens=1000)
        self.assertEqual(bm.get_reserved_budget("SEV-1"), 300)  # 30%
        self.assertEqual(bm.get_reserved_budget("SEV-2"), 250)  # 25%

        # Allocate tokens
        result = bm.allocate_tokens("SEV-1", 100)
        self.assertTrue(result["success"])
        self.assertEqual(bm.get_available_budget("SEV-1"), 200)

        # Over-allocate should fail
        result = bm.allocate_tokens("SEV-1", 500)
        self.assertFalse(result["success"])

    def test_cursor_tracker(self):
        """Test CursorTracker hash verification."""
        from src.state.state_manager import CursorTracker

        tracker = CursorTracker()
        hash1 = tracker.update_cursor_hash("patch1")
        hash2 = tracker.update_cursor_hash("patch2")

        self.assertNotEqual(hash1, hash2)

        # Verify correct hash
        result = tracker.verify_cursor_hash(hash2)
        self.assertTrue(result["valid"])

        # Verify wrong hash
        result = tracker.verify_cursor_hash("wrong_hash")
        self.assertFalse(result["valid"])
        self.assertIn("cursor_drift_detected", result["gap"])

    def test_session_state(self):
        """Test SessionState initialization and methods."""
        from src.state.state_manager import SessionState

        state = SessionState()
        self.assertEqual(state.state, "INIT")
        self.assertIsNotNone(state.session_id)

        # Pass a gate
        state.pass_gate("GATE-00", {"details": "test"})
        self.assertEqual(state.gates["GATE-00"]["status"], "PASS")

        # Add gap
        state.add_gap("[gap: test]")
        self.assertEqual(len(state.gaps), 1)


class TestEventBus(unittest.TestCase):
    """Tests for EventBus module."""

    def test_event_creation(self):
        """Test Event creation and serialization."""
        from src.events.event_bus import Event, EventSeverity

        event = Event(
            event_type="TEST_EVENT",
            data={"key": "value"},
            severity=EventSeverity.INFO
        )

        self.assertEqual(event.event_type, "TEST_EVENT")
        self.assertIn("event_id", event.to_dict())

    def test_event_bus_subscribe(self):
        """Test EventBus subscription and emission."""
        from src.events.event_bus import EventBus, Event, EventSeverity

        bus = EventBus()
        received = []

        def handler(event):
            received.append(event)

        bus.subscribe("TEST", handler)
        bus.emit(Event("TEST", {"data": 1}, EventSeverity.INFO))

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].data["data"], 1)

    def test_event_severity_dispatch(self):
        """Test severity-based dispatch."""
        from src.events.event_bus import EventBus, Event, EventSeverity

        bus = EventBus()
        critical_events = []

        def critical_handler(event):
            critical_events.append(event)

        bus.subscribe_severity(EventSeverity.CRITICAL, critical_handler)

        bus.emit(Event("INFO_EVENT", {}, EventSeverity.INFO))
        self.assertEqual(len(critical_events), 0)

        bus.emit(Event("CRITICAL_EVENT", {}, EventSeverity.CRITICAL))
        self.assertEqual(len(critical_events), 1)


class TestModeAdapter(unittest.TestCase):
    """Tests for ModeAdapter module."""

    def test_mode_presets(self):
        """Test mode presets exist."""
        from src.harness.orchestrator import ModeAdapter

        modes = ModeAdapter.list_modes()
        self.assertIn("direct", modes)
        self.assertIn("auto", modes)
        self.assertIn("manual", modes)

    def test_mode_gate_modification(self):
        """Test gate result modification."""
        from src.harness.orchestrator import ModeAdapter

        # Direct mode - blocking
        adapter = ModeAdapter("direct")
        result = adapter.apply_to_gate("GATE-04", {"status": "FAIL", "reason": "test"})
        self.assertEqual(result["status"], "FAIL")

        # Manual mode - advisory
        adapter = ModeAdapter("manual")
        result = adapter.apply_to_gate("GATE-04", {"status": "FAIL", "reason": "test"})
        self.assertEqual(result["status"], "WARN")
        self.assertEqual(result["mode"], "ADVISORY")


class TestIntentRouter(unittest.TestCase):
    """Tests for IntentRouter module."""

    def test_intent_classification(self):
        """Test intent classification."""
        from src.policy.intent_router import IntentRouter

        router = IntentRouter()

        result = router.classify_intent("Please review this code for security issues")
        self.assertEqual(result.intent, "code_review")
        self.assertGreater(result.confidence, 0)

        result = router.classify_intent("Fix this bug in the authentication")
        self.assertEqual(result.intent, "debugging")

    def test_intent_chain(self):
        """Test chain retrieval."""
        from src.policy.intent_router import IntentRouter

        router = IntentRouter()
        chain = router.get_chain("code_review")

        self.assertIn("security_scan", chain)
        self.assertIn("diff_generator", chain)

    def test_custom_intent(self):
        """Test adding custom intent."""
        from src.policy.intent_router import IntentRouter

        router = IntentRouter()
        router.add_custom_intent(
            "custom_task",
            ["step1", "step2"],
            keywords=["custom", "special"],
            priority=10
        )

        self.assertIn("custom_task", router.list_intents())
        result = router.classify_intent("I need a custom task done")
        self.assertEqual(result.intent, "custom_task")


class TestModelRouter(unittest.TestCase):
    """Tests for ModelRouter module."""

    def test_model_routing(self):
        """Test phase-based model routing."""
        from src.llm.router import ModelRouter

        config = {
            "model_routing": {
                "root_model": {"provider": "openai", "model": "gpt-4"},
                "leaf_model": {"provider": "openai", "model": "gpt-3.5-turbo"}
            }
        }

        router = ModelRouter(config)

        # Phase 0 should use root model
        model = router.get_model_for_phase(0)
        self.assertEqual(model.model, "gpt-4")

        # Phase 4 should use leaf model
        model = router.get_model_for_phase(4)
        self.assertEqual(model.model, "gpt-3.5-turbo")

    def test_fallback_activation(self):
        """Test fallback chain activation."""
        from src.llm.router import ModelRouter

        config = {
            "model_fallback": {
                "enabled": True,
                "chain": ["model-a", "model-b"]
            }
        }

        router = ModelRouter(config)

        self.assertTrue(router.should_fallback(error=Exception("test")))
        next_model = router.activate_fallback("test error")
        self.assertEqual(next_model, "model-a")


class TestValidatorDAG(unittest.TestCase):
    """Tests for ValidatorDAG module."""

    def test_dag_registration(self):
        """Test validator registration."""
        from src.validation.validator_dag import ValidatorDAG

        dag = ValidatorDAG()
        dag.register("validator_a")
        dag.register("validator_b", dependencies=["validator_a"])

        self.assertEqual(len(dag), 2)
        self.assertIn("validator_a", dag)

    def test_cycle_detection(self):
        """Test cycle detection."""
        from src.validation.validator_dag import ValidatorDAG

        dag = ValidatorDAG()
        dag.register("a", dependencies=["b"])
        dag.register("b", dependencies=["a"])

        has_cycle, cycle_path = dag.detect_cycle()
        self.assertTrue(has_cycle)

    def test_topological_order(self):
        """Test topological ordering."""
        from src.validation.validator_dag import ValidatorDAG

        dag = ValidatorDAG()
        dag.register("c", dependencies=["b"])
        dag.register("b", dependencies=["a"])
        dag.register("a")

        order = dag.topological_order()
        self.assertEqual(order.index("a"), 0)
        self.assertEqual(order.index("b"), 1)
        self.assertEqual(order.index("c"), 2)


class TestDiagnosticsListener(unittest.TestCase):
    """Tests for DiagnosticsListener module."""

    def test_gate_fail_handling(self):
        """Test GATE_FAIL event handling."""
        from src.diagnostics.event_listener import DiagnosticsListener
        from src.events.event_bus import Event, EventSeverity

        listener = DiagnosticsListener(max_identical_symptoms=3)

        event = Event(
            event_type="GATE_FAIL",
            data={"gate_id": "GATE-04", "reason": "checksum_mismatch"},
            severity=EventSeverity.CRITICAL
        )

        result = listener.on_gate_fail(event)
        self.assertEqual(result.action, "rescan")
        self.assertEqual(result.cause, "source_modified")

    def test_escalation(self):
        """Test escalation on repeated failures."""
        from src.diagnostics.event_listener import DiagnosticsListener
        from src.events.event_bus import Event, EventSeverity

        listener = DiagnosticsListener(max_identical_symptoms=2)

        event = Event(
            event_type="GATE_FAIL",
            data={"gate_id": "GATE-04", "reason": "test"},
            severity=EventSeverity.CRITICAL
        )

        # First occurrence
        result = listener.on_gate_fail(event)
        self.assertFalse(result.escalation_required)

        # Second occurrence
        result = listener.on_gate_fail(event)
        self.assertTrue(result.escalation_required)
        self.assertIn("human_review_required", result.gap)


class TestSnapshotManager(unittest.TestCase):
    """Tests for SnapshotManager module."""

    def test_snapshot_save_load(self):
        """Test saving and loading snapshots."""
        import tempfile
        from src.planning.state_snapshot import SnapshotManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(Path(tmpdir))

            state = {
                "chunks": {"c1": {"status": "complete"}},
                "gates": {"GATE-00": {"status": "PASS"}},
                "tokens_used": 1000,
                "open_issues": ["issue1"],
                "cursor_hash": "abc123",
                "phase": 2
            }

            path = manager.save_snapshot("node_1", state)
            self.assertTrue(path.exists())

            snapshot = manager.load_snapshot("node_1")
            self.assertEqual(snapshot.tokens_used, 1000)
            self.assertIn("GATE-00", snapshot.gates_passed)

    def test_rollback_plan(self):
        """Test rollback planning."""
        import tempfile
        from src.planning.state_snapshot import SnapshotManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(Path(tmpdir))

            # Save snapshots for nodes 1 and 2
            manager.save_snapshot("node_1", {"tokens_used": 500})
            manager.save_snapshot("node_2", {"tokens_used": 1000})

            # Get rollback plan from node_3 (no snapshot)
            plan = manager.get_rollback_plan("node_3", ["node_1", "node_2", "node_3"])

            self.assertTrue(plan["can_rollback"])
            self.assertEqual(plan["target_node"], "node_2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
