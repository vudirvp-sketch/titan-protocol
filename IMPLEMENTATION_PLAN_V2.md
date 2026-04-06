# TITAN PROTOCOL — IMPROVED IMPLEMENTATION ROADMAP v2.0

**Self-contained execution plan for LLM agent.**
**Updated: 2026-04-07**
**Status: APPROVED FOR IMPLEMENTATION**

---

## IMPROVEMENTS OVER ORIGINAL PLAN

| Issue | Resolution |
|-------|------------|
| Missing test strategy | Added test files per module |
| No task dependencies | Added DEPENDS_ON field |
| VM2 security issues | Replaced with isolated-worker |
| No rollback plan | Added ROLLBACK_STRATEGY per task |
| No config migration | Added config schema updates |
| No benchmarks | Added PERFORMANCE_TARGETS |

---

## TASK DEPENDENCY GRAPH

```
Task 1 (Assessment) ─────────────────────────────────────┐
Task 2 (Evidence Type) ──────────────────────────────────┤
Task 3 (Mode Rules) ─────────────────────────────────────┤
Task 4-5 (EventBus) ──────────────┐                      │
                                  ▼                      │
Task 11 (Diagnostics) ◄───────────┘                      │
                                                         ▼
Task 12 (Cursor Hash) ◄──────────────────────────────────┘
Task 6 (IntentRouter)
Task 7 (ModelRouter)
Task 8 (Budget Allocation)
Task 9 (Validator DAG)
Task 10 (Sandbox) ──► Task 9
Task 13 (DAG Checkpoint)
```

---

## v3.2.3 — PARTIAL IMPLEMENTATIONS COMPLETION

### Task 1: Dual-Axis Scoring (SIGNAL × READINESS)

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 30 min

**Create:** `src/state/assessment.py`
**Test:** `tests/unit/test_assessment.py`

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class SignalStrength(Enum):
    WEAK = 1
    MODERATE = 2
    STRONG = 3

class ReadinessTier(Enum):
    PRODUCTION_READY = "PRODUCTION_READY"
    EXPERIMENTAL = "EXPERIMENTAL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

@dataclass
class AssessmentScore:
    signal: SignalStrength
    readiness: ReadinessTier
    combined_score: float  # 0.0 - 1.0

    @classmethod
    def calculate(cls, volatility: str, confidence: float) -> 'AssessmentScore':
        # Map volatility to signal
        signal_map = {
            "low": SignalStrength.STRONG,
            "medium": SignalStrength.MODERATE,
            "high": SignalStrength.WEAK,
            "V0": SignalStrength.STRONG,
            "V1": SignalStrength.STRONG,
            "V2": SignalStrength.MODERATE,
            "V3": SignalStrength.WEAK
        }
        signal = signal_map.get(volatility.lower(), SignalStrength.MODERATE)

        # Map confidence to readiness
        if confidence >= 0.9:
            readiness = ReadinessTier.PRODUCTION_READY
        elif confidence >= 0.7:
            readiness = ReadinessTier.EXPERIMENTAL
        else:
            readiness = ReadinessTier.REVIEW_REQUIRED

        # Combined score: signal (40%) + confidence (60%)
        combined = (signal.value / 3.0) * 0.4 + confidence * 0.6

        return cls(signal=signal, readiness=readiness, combined_score=combined)

    def to_dict(self) -> dict:
        return {
            "signal": self.signal.name,
            "readiness": self.readiness.value,
            "combined_score": round(self.combined_score, 3)
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'AssessmentScore':
        return cls(
            signal=SignalStrength[data["signal"]],
            readiness=ReadinessTier(data["readiness"]),
            combined_score=data["combined_score"]
        )
```

**COMPLETION_CRITERIA:**
- [ ] `assessment_score` field in SessionState
- [ ] `assessment_score` in metrics.json
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete assessment.py, remove field from SessionState

**PERFORMANCE_TARGET:** < 1ms per calculation

---

### Task 2: Evidence Type Boundaries

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 20 min

**Modify:** `src/state/state_manager.py`
**Test:** `tests/unit/test_state_manager.py`

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class EvidenceType(Enum):
    FACT = "FACT"          # Verified information
    OPINION = "OPINION"    # Subjective assessment
    CODE = "CODE"          # Code snippet
    WARNING = "WARNING"    # Caution note
    STEP = "STEP"          # Procedure step
    EXAMPLE = "EXAMPLE"    # Illustrative example
    GAP = "GAP"            # Missing information

@dataclass
class ReasoningStep:
    content: str
    evidence_type: EvidenceType = EvidenceType.FACT
    confidence: float = 1.0
    source_ref: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "evidence_type": self.evidence_type.value,
            "confidence": self.confidence,
            "source_ref": self.source_ref
        }
```

**COMPLETION_CRITERIA:**
- [ ] `evidence_type` field in ReasoningStep
- [ ] `evidence_type` in QueryResult
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Remove evidence_type from ReasoningStep, keep default behavior

---

### Task 3: Mode-Specific Gate Behavior

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 25 min

**Modify:** `src/harness/orchestrator.py`
**Test:** `tests/unit/test_orchestrator.py`

```python
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class ModeConfig:
    eval_veto_sensitivity: str = "NORMAL"
    gate_03_mode: str = "BLOCKING"
    gate_04_mode: str = "BLOCKING"
    gate_04_threshold: float = 0.75
    requires_human_ack: bool = False

class ModeAdapter:
    """Apply mode-specific gate behavior modifications."""

    MODE_PRESETS = {
        "direct": ModeConfig(),  # Default
        "auto": ModeConfig(
            eval_veto_sensitivity="HIGH",
            gate_04_threshold=0.85  # Stricter
        ),
        "manual": ModeConfig(
            gate_03_mode="ADVISORY",
            gate_04_mode="ADVISORY",
            requires_human_ack=True
        ),
        "interactive": ModeConfig(
            gate_04_mode="ADVISORY",
            requires_human_ack=True
        )
    }

    def __init__(self, mode: str = "direct"):
        self.mode = mode
        self.config = self.MODE_PRESETS.get(mode, ModeConfig())

    def apply_to_gate(self, gate_id: str, base_result: Dict) -> Dict:
        """Apply mode-specific modifications to gate result."""
        result = base_result.copy()

        if gate_id == "GATE-03" and self.config.gate_03_mode == "ADVISORY":
            result["mode"] = "ADVISORY"
            if result.get("status") == "FAIL":
                result["status"] = "WARN"
                result["advisory_note"] = "GATE-03 demoted to ADVISORY in MANUAL mode"

        elif gate_id == "GATE-04":
            if self.config.gate_04_mode == "ADVISORY":
                result["mode"] = "ADVISORY"
            if self.config.gate_04_threshold != 0.75:
                result["threshold"] = self.config.gate_04_threshold

        return result

    def get_modifications(self) -> Dict[str, Any]:
        """Get all mode modifications as dict."""
        return {
            "mode": self.mode,
            "eval_veto_sensitivity": self.config.eval_veto_sensitivity,
            "gate_03_mode": self.config.gate_03_mode,
            "gate_04_mode": self.config.gate_04_mode,
            "gate_04_threshold": self.config.gate_04_threshold,
            "requires_human_ack": self.config.requires_human_ack
        }
```

**COMPLETION_CRITERIA:**
- [ ] Mode affects gate thresholds as documented
- [ ] AUTO mode has stricter GATE-04
- [ ] MANUAL mode demotes GATE-03/04 to ADVISORY
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Remove ModeAdapter, use default behavior

---

### Task 4-5: Event Severity + Handler Failure Escalation

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 40 min

**Modify:** `src/events/event_bus.py`
**Test:** `tests/unit/test_event_bus.py`

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable, Any, Optional
import logging

class EventSeverity(Enum):
    CRITICAL = 1  # GATE_FAIL, BUDGET_EXCEEDED - sync dispatch
    WARN = 2      # GATE_WARN, ANOMALY_DETECTED
    INFO = 3      # GATE_PASS, CURSOR_UPDATED
    DEBUG = 4     # Detailed trace events

@dataclass
class Event:
    event_type: str
    data: Dict[str, Any]
    severity: EventSeverity = EventSeverity.INFO
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    source: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "severity": self.severity.name,
            "timestamp": self.timestamp,
            "source": self.source
        }

class EventBus:
    """Event bus with severity-based dispatch and handler failure escalation."""

    def __init__(self, config: Dict = None):
        self.config = config or {}
        self._handlers: Dict[str, List[Callable]] = {}
        self._severity_handlers: Dict[EventSeverity, List[Callable]] = {}
        self._logger = logging.getLogger(__name__)
        self._handler_failure_action = self.config.get("handler_failure_action", "log")

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe handler to event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def subscribe_severity(self, severity: EventSeverity, handler: Callable) -> None:
        """Subscribe handler to all events of given severity."""
        if severity not in self._severity_handlers:
            self._severity_handlers[severity] = []
        self._severity_handlers[severity].append(handler)

    def emit(self, event: Event) -> None:
        """Emit event with handler failure escalation."""
        # Dispatch to type-specific handlers
        for handler in self._get_handlers(event.event_type):
            self._safe_dispatch(handler, event)

        # Dispatch to severity-specific handlers
        for handler in self._severity_handlers.get(event.severity, []):
            self._safe_dispatch(handler, event)

        # Sync dispatch for CRITICAL events
        if event.severity == EventSeverity.CRITICAL:
            self._dispatch_critical(event)

    def _get_handlers(self, event_type: str) -> List[Callable]:
        """Get handlers for event type, including wildcard."""
        handlers = self._handlers.get(event_type, [])
        wildcard_handlers = self._handlers.get("*", [])
        return handlers + wildcard_handlers

    def _safe_dispatch(self, handler: Callable, event: Event) -> None:
        """Dispatch with failure handling."""
        try:
            handler(event)
        except Exception as e:
            self._handle_handler_failure(handler, e, event)

    def _handle_handler_failure(self, handler: Callable, error: Exception, event: Event) -> None:
        """Handle handler failure with escalation."""
        self._logger.error(f"Handler {handler.__name__} failed: {error}")

        # Emit failure event
        failure_event = Event(
            event_type="EVENT_HANDLER_FAILURE",
            data={
                "failed_handler": handler.__name__,
                "original_event": event.event_type,
                "error": str(error),
                "error_type": type(error).__name__
            },
            severity=EventSeverity.CRITICAL,
            source="EventBus"
        )
        self._dispatch_critical(failure_event)

        # Escalate based on config
        action = self._handler_failure_action
        if action == "abort":
            raise error
        elif action == "warn":
            self._logger.warning(f"Handler failure escalated: {handler.__name__}")

    def _dispatch_critical(self, event: Event) -> None:
        """Synchronous dispatch for CRITICAL events."""
        for handler in self._get_handlers(event.event_type):
            try:
                handler(event)
            except Exception as e:
                # CRITICAL handler failure - log and continue
                self._logger.critical(f"CRITICAL handler failed: {e}")
```

**COMPLETION_CRITERIA:**
- [ ] Events include severity field
- [ ] CRITICAL events dispatch synchronously
- [ ] Handler failure emits `EVENT_HANDLER_FAILURE`
- [ ] `[gap: handler_critical_failure]` on handler crash
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Revert to simple event bus without severity

**PERFORMANCE_TARGET:** < 5ms event dispatch, < 50ms for CRITICAL events

---

### Task 6: IntentRouter Module

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 35 min

**Create:** `src/policy/intent_router.py`
**Test:** `tests/unit/test_intent_router.py`

```python
"""
Intent-based policy chain selection.
Routes execution based on intent_classification.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
import re

# Default policy chains per intent
INTENT_CHAINS = {
    "code_review": ["security_scan", "style_check", "diff_generator"],
    "refactor": ["dependency_analysis", "impact_assessment", "diff_generator"],
    "documentation": ["reference_collector", "doc_generator"],
    "debugging": ["error_analysis", "trace_collector", "fix_generator"],
    "feature_add": ["impact_assessment", "implementation_planner"],
    "test_gen": ["coverage_analysis", "test_generator"],
    "migration": ["compatibility_check", "migration_planner"]
}

@dataclass
class IntentResult:
    intent: str
    confidence: float
    keywords_matched: List[str]
    chain: List[str]

class IntentRouter:
    """Select policy chain based on intent classification."""

    KEYWORDS = {
        "code_review": ["review", "check", "audit", "analyze", "inspect"],
        "refactor": ["refactor", "restructure", "reorganize", "rewrite"],
        "documentation": ["document", "readme", "doc", "comment", "describe"],
        "debugging": ["debug", "fix", "error", "bug", "issue", "problem"],
        "feature_add": ["add", "implement", "create", "new feature", "extend"],
        "test_gen": ["test", "spec", "coverage", "unit test"],
        "migration": ["migrate", "upgrade", "port", "convert"]
    }

    def __init__(self, chains: Dict[str, List[str]] = None):
        self.chains = chains or INTENT_CHAINS

    def classify_intent(self, query: str) -> IntentResult:
        """Classify intent from query text."""
        query_lower = query.lower()
        best_intent = "code_review"  # Default
        best_score = 0
        matched_keywords = []

        for intent, keywords in self.KEYWORDS.items():
            matches = [kw for kw in keywords if kw in query_lower]
            score = len(matches)

            if score > best_score:
                best_score = score
                best_intent = intent
                matched_keywords = matches

        confidence = min(1.0, best_score / 3.0) if best_score > 0 else 0.3

        return IntentResult(
            intent=best_intent,
            confidence=confidence,
            keywords_matched=matched_keywords,
            chain=self.get_chain(best_intent)
        )

    def get_chain(self, intent: str) -> List[str]:
        """Get policy chain for intent type."""
        return self.chains.get(intent, self.chains.get("code_review", []))

    def add_custom_intent(self, intent: str, chain: List[str], keywords: List[str] = None) -> None:
        """Add custom intent with chain and optional keywords."""
        self.chains[intent] = chain
        if keywords:
            self.KEYWORDS[intent] = keywords
```

**COMPLETION_CRITERIA:**
- [ ] Intent classification drives policy selection
- [ ] Custom intents can be added
- [ ] Confidence score returned
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete intent_router.py, use default chain

---

### Task 7: ModelRouter with Fallback Chain

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 45 min

**Create:** `src/llm/router.py`
**Test:** `tests/unit/test_router.py`

```python
"""
Model routing with fallback chain support.
Config-driven root/leaf model selection.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

@dataclass
class ModelConfig:
    provider: str
    model: str
    max_tokens: int
    fallback: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "fallback": self.fallback
        }

@dataclass
class FallbackState:
    current_index: int = 0
    fallback_count: int = 0
    last_fallback_reason: Optional[str] = None
    last_fallback_time: Optional[str] = None

class ModelRouter:
    """Route LLM calls with fallback chain."""

    # Phases that use root model (orchestration)
    ROOT_PHASES = {0, 1, 2, 3, 5}
    # Phases that use leaf model (chunk processing)
    LEAF_PHASES = {4}

    def __init__(self, config: Dict):
        self.config = config
        self._logger = logging.getLogger(__name__)

        # Parse model configs
        routing = config.get("model_routing", {})
        self.root_model = self._parse_model(routing.get("root_model", {}))
        self.leaf_model = self._parse_model(routing.get("leaf_model", {}))

        # Fallback configuration
        fb_config = config.get("model_fallback", {})
        self.fallback_chain = fb_config.get("chain", [])
        self.fallback_enabled = fb_config.get("enabled", False)
        self.fallback_state = FallbackState()

        # Triggers
        self.triggers = fb_config.get("triggers", {})
        self.timeout_ms = self.triggers.get("timeout_ms", 30000)
        self.error_rate_threshold = self.triggers.get("error_rate_threshold", 0.3)

    def _parse_model(self, cfg: Dict) -> ModelConfig:
        """Parse model configuration."""
        if isinstance(cfg, str):
            return ModelConfig(provider="default", model=cfg, max_tokens=4096)
        return ModelConfig(
            provider=cfg.get("provider", "openai"),
            model=cfg.get("model", "gpt-4"),
            max_tokens=cfg.get("max_tokens", 4096),
            fallback=cfg.get("fallback", [])
        )

    def get_model_for_phase(self, phase: int) -> ModelConfig:
        """Get appropriate model for processing phase."""
        if phase in self.ROOT_PHASES:
            return self.root_model
        return self.leaf_model

    def should_fallback(self, error: Optional[Exception] = None,
                        latency_ms: int = 0,
                        token_budget_exceeded: bool = False) -> bool:
        """Determine if fallback should activate."""
        if not self.fallback_enabled:
            return False

        # Check timeout
        if latency_ms > self.timeout_ms:
            self._logger.info(f"Fallback triggered: timeout ({latency_ms}ms > {self.timeout_ms}ms)")
            return True

        # Check token budget
        if token_budget_exceeded:
            self._logger.info("Fallback triggered: token budget exceeded")
            return True

        # Check error
        if error:
            self._logger.info(f"Fallback triggered: error ({type(error).__name__})")
            return True

        return False

    def activate_fallback(self, reason: str = "unknown") -> Optional[str]:
        """Activate next fallback model."""
        if not self.fallback_chain:
            return None

        if self.fallback_state.current_index < len(self.fallback_chain):
            next_model = self.fallback_chain[self.fallback_state.current_index]
            self.fallback_state.current_index += 1
            self.fallback_state.fallback_count += 1
            self.fallback_state.last_fallback_reason = reason
            self.fallback_state.last_fallback_time = datetime.utcnow().isoformat() + "Z"

            self._logger.warning(f"Activated fallback model: {next_model} (reason: {reason})")
            return next_model

        self._logger.error("No more fallback models available")
        return None

    def reset_fallback(self) -> None:
        """Reset fallback state for new operation."""
        self.fallback_state = FallbackState()

    def get_status(self) -> Dict:
        """Get current router status."""
        return {
            "root_model": self.root_model.to_dict(),
            "leaf_model": self.leaf_model.to_dict(),
            "fallback_enabled": self.fallback_enabled,
            "fallback_chain": self.fallback_chain,
            "fallback_state": {
                "current_index": self.fallback_state.current_index,
                "fallback_count": self.fallback_state.fallback_count,
                "last_fallback_reason": self.fallback_state.last_fallback_reason
            }
        }
```

**COMPLETION_CRITERIA:**
- [ ] Fallback chain activates on timeout/error
- [ ] Root/leaf model routing works
- [ ] Status tracking implemented
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete router.py, use single model

---

### Task 8: Per-Tier Token Budget Allocation

**DEPENDS_ON:** Task 1 (Assessment)
**PRIORITY:** HIGH
**ESTIMATED:** 30 min

**Modify:** `src/state/state_manager.py`
**Test:** `tests/unit/test_state_manager.py`

```python
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class BudgetAllocation:
    """Token budget allocation per severity level."""
    sev_1_ratio: float = 0.30  # 30% reserved for SEV-1
    sev_2_ratio: float = 0.25  # 25% reserved for SEV-2
    sev_3_4_ratio: float = 0.45  # 45% pool for SEV-3/4

    def to_dict(self) -> Dict:
        return {
            "sev_1_ratio": self.sev_1_ratio,
            "sev_2_ratio": self.sev_2_ratio,
            "sev_3_4_ratio": self.sev_3_4_ratio
        }

class BudgetManager:
    """Manage per-severity token budget allocation."""

    def __init__(self, max_tokens: int, allocation: BudgetAllocation = None):
        self.max_tokens = max_tokens
        self.allocation = allocation or BudgetAllocation()
        self._sev_tokens_used: Dict[str, int] = {
            "SEV-1": 0,
            "SEV-2": 0,
            "SEV-3": 0,
            "SEV-4": 0
        }
        self._total_used = 0

    def get_reserved_budget(self, severity: str) -> int:
        """Get total reserved budget for severity level."""
        if severity == "SEV-1":
            return int(self.max_tokens * self.allocation.sev_1_ratio)
        elif severity == "SEV-2":
            return int(self.max_tokens * self.allocation.sev_2_ratio)
        else:  # SEV-3 or SEV-4
            return int(self.max_tokens * self.allocation.sev_3_4_ratio)

    def get_available_budget(self, severity: str) -> int:
        """Get remaining budget for severity level."""
        reserved = self.get_reserved_budget(severity)
        used = self._sev_tokens_used.get(severity, 0)
        return max(0, reserved - used)

    def allocate_tokens(self, severity: str, tokens: int) -> Dict:
        """Allocate tokens for a severity level operation."""
        available = self.get_available_budget(severity)

        if tokens > available:
            return {
                "success": False,
                "allocated": 0,
                "requested": tokens,
                "available": available,
                "severity": severity,
                "error": f"Insufficient budget for {severity}: {tokens} > {available}"
            }

        self._sev_tokens_used[severity] += tokens
        self._total_used += tokens

        return {
            "success": True,
            "allocated": tokens,
            "severity": severity,
            "remaining": self.get_available_budget(severity)
        }

    def get_status(self) -> Dict:
        """Get budget status for all severity levels."""
        return {
            "max_tokens": self.max_tokens,
            "total_used": self._total_used,
            "total_remaining": self.max_tokens - self._total_used,
            "allocation": self.allocation.to_dict(),
            "per_severity": {
                sev: {
                    "reserved": self.get_reserved_budget(sev),
                    "used": used,
                    "available": self.get_available_budget(sev)
                }
                for sev, used in self._sev_tokens_used.items()
            }
        }

    def can_afford(self, severity: str, tokens: int) -> bool:
        """Check if operation is affordable within budget."""
        return tokens <= self.get_available_budget(severity)
```

**COMPLETION_CRITERIA:**
- [ ] Budget reserved per severity level
- [ ] SEV-1 gets 30%, SEV-2 gets 25%, SEV-3/4 get 45%
- [ ] Allocation tracking works
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Use simple total budget tracking

---

### Task 9: Validator Dependency DAG

**DEPENDS_ON:** None
**PRIORITY:** HIGH
**ESTIMATED:** 40 min

**Create:** `src/validation/validator_dag.py`
**Test:** `tests/unit/test_validator_dag.py`

```python
"""
Validator dependency resolution.
Prevents circular validator calls.
"""

from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class ValidationResult:
    valid: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    cycle_detected: bool = False
    cycle_path: List[str] = field(default_factory=list)

class ValidatorDAG:
    """Manage validator dependencies and execution order."""

    def __init__(self):
        self.graph: Dict[str, List[str]] = defaultdict(list)
        self.validators: Set[str] = set()
        self._execution_cache: Optional[List[str]] = None

    def register(self, validator_id: str, dependencies: List[str] = None) -> None:
        """Register validator with its dependencies."""
        self.validators.add(validator_id)
        for dep in (dependencies or []):
            self.graph[validator_id].append(dep)
            self.validators.add(dep)
        self._execution_cache = None  # Invalidate cache

    def unregister(self, validator_id: str) -> None:
        """Unregister a validator."""
        self.validators.discard(validator_id)
        if validator_id in self.graph:
            del self.graph[validator_id]
        self._execution_cache = None

    def detect_cycle(self) -> Tuple[bool, List[str]]:
        """Detect if graph contains a cycle."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {v: WHITE for v in self.validators}

        def dfs(node: str, path: List[str]) -> List[str]:
            color[node] = GRAY
            for neighbor in self.graph.get(node, []):
                if color[neighbor] == GRAY:
                    return path + [neighbor]  # Cycle found
                if color[neighbor] == WHITE:
                    cycle = dfs(neighbor, path + [node])
                    if cycle:
                        return cycle
            color[node] = BLACK
            return []

        for validator in self.validators:
            if color[validator] == WHITE:
                cycle = dfs(validator, [])
                if cycle:
                    return True, cycle

        return False, []

    def topological_order(self) -> List[str]:
        """Get validators in topological order."""
        if self._execution_cache:
            return self._execution_cache

        result = []
        visited = set()
        temp_visited = set()

        def visit(node: str) -> bool:
            if node in temp_visited:
                return False  # Cycle detected
            if node in visited:
                return True

            temp_visited.add(node)
            for dep in self.graph.get(node, []):
                if not visit(dep):
                    return False

            temp_visited.remove(node)
            visited.add(node)
            result.append(node)
            return True

        for validator in sorted(self.validators):  # Sort for deterministic order
            if validator not in visited:
                if not visit(validator):
                    return []  # Cycle detected

        self._execution_cache = result
        return result

    def get_dependencies(self, validator_id: str) -> List[str]:
        """Get all dependencies for a validator (transitive)."""
        deps = set()
        to_visit = list(self.graph.get(validator_id, []))

        while to_visit:
            dep = to_visit.pop()
            if dep not in deps:
                deps.add(dep)
                to_visit.extend(self.graph.get(dep, []))

        return list(deps)

    def validate_graph(self) -> ValidationResult:
        """Validate the DAG and return result."""
        has_cycle, cycle_path = self.detect_cycle()

        if has_cycle:
            return ValidationResult(
                valid=False,
                violations=[f"[gap: validator_cycle_detected] Cycle: {' -> '.join(cycle_path)}"],
                cycle_detected=True,
                cycle_path=cycle_path
            )

        order = self.topological_order()
        return ValidationResult(
            valid=True,
            execution_order=order,
            warnings=[] if len(order) == len(self.validators) else
                [f"Some validators not reachable: {self.validators - set(order)}"]
        )

    def clear(self) -> None:
        """Clear all validators."""
        self.graph.clear()
        self.validators.clear()
        self._execution_cache = None
```

**COMPLETION_CRITERIA:**
- [ ] `[gap: validator_cycle_detected]` on circular deps
- [ ] Topological order works
- [ ] Transitive dependencies resolved
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete validator_dag.py, run validators in registration order

---

### Task 10: Validator Sandboxing (IMPROVED)

**DEPENDS_ON:** Task 9
**PRIORITY:** HIGH
**ESTIMATED:** 50 min

**Create:** `src/validation/sandbox.py`
**Test:** `tests/unit/test_sandbox.py`

**SECURITY IMPROVEMENT:** Replaced deprecated VM2 with Python subprocess isolation

```python
"""
Sandboxed validator execution.
Isolates untrusted validators in subprocess.
"""

import subprocess
import json
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging
import hashlib

@dataclass
class SandboxResult:
    valid: bool
    violations: list
    error: Optional[str] = None
    execution_time_ms: int = 0
    timeout: bool = False

class ValidatorSandbox:
    """Execute validators in isolated subprocess context."""

    def __init__(self, timeout_ms: int = 5000, max_output_size: int = 1024 * 1024):
        self.timeout_ms = timeout_ms
        self.max_output_size = max_output_size
        self._logger = logging.getLogger(__name__)

    def run_python_validator(self, script_path: Path, content: str,
                             context: Dict = None) -> SandboxResult:
        """Run Python validator in isolated subprocess."""
        import time
        start_time = time.time()

        # Create wrapper script
        wrapper = self._create_python_wrapper(script_path, content, context or {})

        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(wrapper)
                wrapper_path = f.name

            result = subprocess.run(
                ['python', wrapper_path],
                capture_output=True,
                text=True,
                timeout=self.timeout_ms / 1000
            )

            os.unlink(wrapper_path)

            execution_time = int((time.time() - start_time) * 1000)

            if result.returncode != 0:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"Validator failed: {result.stderr}",
                    execution_time_ms=execution_time
                )

            output = json.loads(result.stdout)
            return SandboxResult(
                valid=output.get("valid", False),
                violations=output.get("violations", []),
                execution_time_ms=execution_time
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                valid=False,
                violations=[],
                error="Validator timeout",
                timeout=True,
                execution_time_ms=self.timeout_ms
            )
        except json.JSONDecodeError as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=f"Invalid JSON output: {e}"
            )
        except Exception as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=str(e)
            )

    def run_js_validator(self, script_path: Path, content: str,
                         context: Dict = None) -> SandboxResult:
        """Run JS validator in Node.js isolated-vm (requires isolated-vm package)."""
        import time
        start_time = time.time()

        # Check if isolated-vm is available
        try:
            import subprocess
            result = subprocess.run(['node', '-e', 'require("isolated-vm")'],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error="isolated-vm not available. Install with: npm install isolated-vm"
                )
        except Exception as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=f"Node.js not available: {e}"
            )

        # Create isolated VM wrapper
        wrapper = self._create_js_wrapper(script_path, content, context or {})

        try:
            result = subprocess.run(
                ['node', '-e', wrapper],
                capture_output=True,
                text=True,
                timeout=self.timeout_ms / 1000
            )

            execution_time = int((time.time() - start_time) * 1000)

            if result.returncode != 0:
                return SandboxResult(
                    valid=False,
                    violations=[],
                    error=f"Validator failed: {result.stderr}",
                    execution_time_ms=execution_time
                )

            output = json.loads(result.stdout)
            return SandboxResult(
                valid=output.get("valid", False),
                violations=output.get("violations", []),
                execution_time_ms=execution_time
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                valid=False,
                violations=[],
                error="Validator timeout",
                timeout=True,
                execution_time_ms=self.timeout_ms
            )
        except Exception as e:
            return SandboxResult(
                valid=False,
                violations=[],
                error=str(e)
            )

    def _create_python_wrapper(self, script_path: Path, content: str,
                               context: Dict) -> str:
        """Create isolated Python wrapper script."""
        return f'''
import json
import sys

# Read validator
with open("{script_path}") as f:
    validator_code = f.read()

# Execute in restricted globals
restricted_globals = {{
    "__builtins__": {{
        "True": True, "False": False, "None": None,
        "len": len, "str": str, "int": int, "float": float,
        "list": list, "dict": dict, "set": set, "tuple": tuple,
        "range": range, "enumerate": enumerate, "zip": zip,
        "isinstance": isinstance, "hasattr": hasattr,
        "json": json
    }},
    "content": {json.dumps(content)},
    "context": {json.dumps(context)}
}}

try:
    exec(validator_code, restricted_globals)
    validator = restricted_globals.get("validator", restricted_globals.get("validate"))
    if callable(validator):
        result = validator(content, context)
    else:
        result = {{"valid": True, "violations": []}}
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"valid": False, "violations": [str(e)]}}))
'''

    def _create_js_wrapper(self, script_path: Path, content: str,
                           context: Dict) -> str:
        """Create isolated-vm JS wrapper script."""
        return f'''
const ivm = require('isolated-vm');

async function run() {{
    const isolate = new ivm.Isolate({{ memoryLimit: 128 }});
    const context = await isolate.createContext();

    // Setup globals
    await context.eval(`
        globalThis.content = {json.dumps(content)};
        globalThis.context = {json.dumps(context)};
    `);

    // Load and execute validator
    const fs = require('fs');
    const code = fs.readFileSync('{script_path}', 'utf8');
    await context.eval(code);

    // Get result
    const result = await context.eval('typeof validate === "function" ? validate(content, context) : {{ valid: true }}');
    console.log(JSON.stringify(result));
}}

run().catch(e => console.log(JSON.stringify({{ valid: false, violations: [e.message] }})));
'''
```

**COMPLETION_CRITERIA:**
- [ ] Python validators run in subprocess isolation
- [ ] JS validators run in isolated-vm (not VM2!)
- [ ] Timeout enforcement works
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete sandbox.py, run validators directly (unsafe)

**SECURITY_NOTES:**
- VM2 removed due to CVE vulnerabilities
- isolated-vm provides true process isolation
- Memory limits enforced

---

### Task 11: DIAGNOSTICS_MODULE as EventBus Listener

**DEPENDS_ON:** Task 4-5 (EventBus)
**PRIORITY:** HIGH
**ESTIMATED:** 35 min

**Create:** `src/diagnostics/event_listener.py`
**Test:** `tests/unit/test_diagnostics.py`

```python
"""
Diagnostics module listening to gate failures.
Escalates to human review on repeated symptoms.
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import logging

@dataclass
class DiagnosticResult:
    action: str
    cause: str
    symptom: str
    occurrences: int
    gap: Optional[str] = None
    escalation_required: bool = False

class DiagnosticsListener:
    """Listen to gate failures and diagnose patterns."""

    DEFAULT_RULES = {
        "gate_fail_patterns": {
            "GATE-00": {
                "symptoms": {
                    "nav_map_missing": {"cause": "chunking_failed", "action": "rechunk"},
                    "index_incomplete": {"cause": "incomplete_scan", "action": "rescan"}
                }
            },
            "GATE-01": {
                "symptoms": {
                    "pattern_not_found": {"cause": "invalid_pattern", "action": "update_pattern"},
                    "scan_timeout": {"cause": "file_too_large", "action": "reduce_chunk_size"}
                }
            },
            "GATE-04": {
                "symptoms": {
                    "checksum_mismatch": {"cause": "source_modified", "action": "rescan"},
                    "validation_failed": {"cause": "invalid_patch", "action": "retry_with_context"},
                    "sev1_gaps_exceeded": {"cause": "critical_issues", "action": "fix_sev1_first"},
                    "sev2_gaps_exceeded": {"cause": "high_priority_issues", "action": "fix_sev2_first"}
                }
            },
            "GATE-05": {
                "symptoms": {
                    "artifacts_missing": {"cause": "generation_failed", "action": "regenerate"},
                    "hygiene_failed": {"cause": "cleanup_error", "action": "manual_cleanup"}
                }
            }
        }
    }

    def __init__(self, rules_path: Path = None, max_identical_symptoms: int = 3):
        self.rules = self._load_rules(rules_path)
        self.symptom_counts: Dict[str, int] = defaultdict(int)
        self.max_identical_symptoms = max_identical_symptoms
        self._logger = logging.getLogger(__name__)
        self._symptom_history: List[Dict] = []

    def _load_rules(self, path: Path) -> Dict:
        """Load diagnostic rules from YAML."""
        if path and path.exists():
            with open(path) as f:
                return yaml.safe_load(f)
        return self.DEFAULT_RULES

    def on_gate_fail(self, event) -> DiagnosticResult:
        """Handle GATE_FAIL event."""
        gate_id = event.data.get("gate_id", "UNKNOWN")
        reason = event.data.get("reason", "unknown")
        details = event.data.get("details", {})

        symptom_key = f"{gate_id}:{reason}"
        self.symptom_counts[symptom_key] += 1

        # Record history
        self._symptom_history.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "gate_id": gate_id,
            "reason": reason,
            "count": self.symptom_counts[symptom_key]
        })

        # Check if escalation needed
        if self.symptom_counts[symptom_key] >= self.max_identical_symptoms:
            self._logger.warning(f"Escalation required: {symptom_key} occurred {self.symptom_counts[symptom_key]} times")
            return DiagnosticResult(
                action="escalate",
                cause="repeated_failure",
                symptom=symptom_key,
                occurrences=self.symptom_counts[symptom_key],
                gap="[gap: human_review_required]",
                escalation_required=True
            )

        # Apply diagnostic rule
        rule = self.rules.get("gate_fail_patterns", {}).get(gate_id, {})
        symptom_rule = rule.get("symptoms", {}).get(reason, {})

        return DiagnosticResult(
            action=symptom_rule.get("action", "retry"),
            cause=symptom_rule.get("cause", "unknown"),
            symptom=symptom_key,
            occurrences=self.symptom_counts[symptom_key]
        )

    def on_event(self, event) -> Optional[DiagnosticResult]:
        """Generic event handler."""
        if event.event_type == "GATE_FAIL":
            return self.on_gate_fail(event)
        return None

    def get_symptom_report(self) -> Dict:
        """Get report of all symptoms."""
        return {
            "symptom_counts": dict(self.symptom_counts),
            "total_failures": sum(self.symptom_counts.values()),
            "unique_symptoms": len(self.symptom_counts),
            "history": self._symptom_history[-20:]  # Last 20 events
        }

    def reset(self) -> None:
        """Reset symptom tracking."""
        self.symptom_counts.clear()
        self._symptom_history.clear()
```

**COMPLETION_CRITERIA:**
- [ ] Auto-escalate to human review on repeated failures
- [ ] Diagnostic rules loaded from YAML
- [ ] Symptom history tracked
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete event_listener.py, remove EventBus subscription

---

### Task 12: Cursor Hash Verification

**DEPENDS_ON:** Task 1, Task 2
**PRIORITY:** HIGH
**ESTIMATED:** 30 min

**Modify:** `src/state/state_manager.py`

```python
import hashlib
from typing import Dict, Optional

class CursorTracker:
    """Track cursor position with hash verification."""

    def __init__(self):
        self.cursor_hash: Optional[str] = None
        self.last_patch_hash: Optional[str] = None
        self._patch_history: List[str] = []

    def update_cursor_hash(self, patch_content: str) -> str:
        """Update cursor hash after patch application."""
        combined = f"{self.last_patch_hash or 'init'}:{patch_content}"
        self.cursor_hash = hashlib.sha256(combined.encode()).hexdigest()[:32]
        self.last_patch_hash = self.cursor_hash
        self._patch_history.append(self.cursor_hash)
        return self.cursor_hash

    def verify_cursor_hash(self, expected_hash: str) -> Dict:
        """Verify cursor hash on resume."""
        if self.cursor_hash != expected_hash:
            return {
                "valid": False,
                "gap": "[gap: cursor_drift_detected]",
                "expected": expected_hash,
                "actual": self.cursor_hash,
                "patch_count": len(self._patch_history)
            }
        return {"valid": True}

    def get_state(self) -> Dict:
        """Get cursor state for checkpoint."""
        return {
            "cursor_hash": self.cursor_hash,
            "last_patch_hash": self.last_patch_hash,
            "patch_count": len(self._patch_history)
        }

    def restore_state(self, state: Dict) -> None:
        """Restore cursor state from checkpoint."""
        self.cursor_hash = state.get("cursor_hash")
        self.last_patch_hash = state.get("last_patch_hash")
```

**COMPLETION_CRITERIA:**
- [ ] `EVENT_CURSOR_DRIFT` emitted on mismatch
- [ ] Cursor state saved in checkpoint
- [ ] Verification on resume works
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Remove CursorTracker, use simple cursor position

---

### Task 13: DAG Checkpointing with Per-Node Rollback

**DEPENDS_ON:** Task 12
**PRIORITY:** HIGH
**ESTIMATED:** 45 min

**Create:** `src/planning/state_snapshot.py`
**Test:** `tests/unit/test_state_snapshot.py`

```python
"""
State snapshots for DAG node rollback.
Enables partial recovery on failure.
"""

import json
from pathlib import Path
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict, field
from datetime import datetime
import logging

@dataclass
class StateSnapshot:
    node_id: str
    timestamp: str
    chunks_state: Dict
    gates_passed: List[str]
    tokens_used: int
    open_issues: List[str]
    cursor_hash: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'StateSnapshot':
        return cls(**data)

class SnapshotManager:
    """Manage state snapshots for rollback."""

    def __init__(self, snapshot_dir: Path, max_snapshots: int = 50):
        self.snapshot_dir = snapshot_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.max_snapshots = max_snapshots
        self._logger = logging.getLogger(__name__)

    def save_snapshot(self, node_id: str, state: Dict) -> Path:
        """Save state snapshot before node execution."""
        snapshot = StateSnapshot(
            node_id=node_id,
            timestamp=datetime.utcnow().isoformat() + "Z",
            chunks_state=state.get("chunks", {}),
            gates_passed=[g for g, s in state.get("gates", {}).items()
                         if s.get("status") == "PASS"],
            tokens_used=state.get("tokens_used", 0),
            open_issues=state.get("open_issues", []),
            cursor_hash=state.get("cursor_hash")
        )

        path = self.snapshot_dir / f"{node_id}.json"
        with open(path, 'w') as f:
            json.dump(snapshot.to_dict(), f, indent=2)

        self._logger.info(f"Saved snapshot: {node_id}")
        self._cleanup_old_snapshots()
        return path

    def load_snapshot(self, node_id: str) -> Optional[StateSnapshot]:
        """Load snapshot for rollback."""
        path = self.snapshot_dir / f"{node_id}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            self._logger.info(f"Loaded snapshot: {node_id}")
            return StateSnapshot.from_dict(data)
        return None

    def delete_snapshot(self, node_id: str) -> bool:
        """Delete a snapshot."""
        path = self.snapshot_dir / f"{node_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def find_nearest_stable(self, current_node: str, dag_nodes: List[str]) -> Optional[str]:
        """Find nearest stable node for rollback."""
        try:
            current_idx = dag_nodes.index(current_node)
        except ValueError:
            return None

        for i in range(current_idx - 1, -1, -1):
            node = dag_nodes[i]
            if self.load_snapshot(node):
                return node
        return None

    def list_snapshots(self) -> List[str]:
        """List all saved snapshot IDs."""
        return [p.stem for p in self.snapshot_dir.glob("*.json")]

    def get_rollback_plan(self, current_node: str, dag_nodes: List[str]) -> Dict:
        """Get rollback plan from current node."""
        nearest = self.find_nearest_stable(current_node, dag_nodes)
        if not nearest:
            return {
                "can_rollback": False,
                "reason": "No stable snapshot found"
            }

        snapshot = self.load_snapshot(nearest)
        return {
            "can_rollback": True,
            "target_node": nearest,
            "snapshot": snapshot.to_dict() if snapshot else None,
            "nodes_to_reexecute": dag_nodes[dag_nodes.index(nearest)+1:
                                            dag_nodes.index(current_node)+1]
        }

    def _cleanup_old_snapshots(self) -> None:
        """Remove old snapshots if count exceeds max."""
        snapshots = sorted(self.snapshot_dir.glob("*.json"),
                         key=lambda p: p.stat().st_mtime)
        while len(snapshots) > self.max_snapshots:
            oldest = snapshots.pop(0)
            oldest.unlink()
            self._logger.debug(f"Removed old snapshot: {oldest.stem}")
```

**COMPLETION_CRITERIA:**
- [ ] Rollback to nearest stable node on failure
- [ ] Snapshot state saved correctly
- [ ] Cleanup of old snapshots works
- [ ] Unit tests pass

**ROLLBACK_STRATEGY:** Delete state_snapshot.py, use session-level checkpoint only

---

## TEST FILES TO CREATE

```
tests/unit/test_assessment.py
tests/unit/test_state_manager.py
tests/unit/test_orchestrator.py
tests/unit/test_event_bus.py
tests/unit/test_intent_router.py
tests/unit/test_router.py
tests/unit/test_validator_dag.py
tests/unit/test_sandbox.py
tests/unit/test_diagnostics.py
tests/unit/test_state_snapshot.py
tests/integration/test_full_pipeline.py
```

---

## CONFIG SCHEMA ADDITIONS

Add to `schemas/config.schema.json`:

```json
{
  "properties": {
    "assessment": {
      "type": "object",
      "properties": {
        "signal_threshold": {"type": "number"},
        "readiness_threshold": {"type": "number"}
      }
    },
    "mode": {
      "type": "object",
      "properties": {
        "current": {"enum": ["direct", "auto", "manual", "interactive"]},
        "presets_dir": {"type": "string"}
      }
    },
    "model_routing": {
      "type": "object",
      "properties": {
        "root_model": {"type": "string"},
        "leaf_model": {"type": "string"}
      }
    },
    "budget": {
      "type": "object",
      "properties": {
        "sev_allocation": {
          "type": "object",
          "properties": {
            "sev_1_ratio": {"type": "number"},
            "sev_2_ratio": {"type": "number"},
            "sev_3_4_ratio": {"type": "number"}
          }
        }
      }
    },
    "sandbox": {
      "type": "object",
      "properties": {
        "timeout_ms": {"type": "integer"},
        "memory_limit_mb": {"type": "integer"}
      }
    }
  }
}
```

---

## EXECUTION ORDER

1. **Phase 1 (Independent):** Tasks 1, 2, 3, 4-5, 6, 7, 9
2. **Phase 2 (Dependent on Phase 1):** Tasks 8, 10, 11, 12
3. **Phase 3 (Dependent on Phase 2):** Task 13

---

## VERIFICATION CHECKLIST

After each task:
- [ ] Code compiles without errors
- [ ] Unit tests pass
- [ ] No regressions in existing tests
- [ ] Documentation updated
- [ ] Config schema updated (if needed)

---

**Plan Status:** IMPROVED AND READY FOR IMPLEMENTATION
**Estimated Total Time:** 6-8 hours for v3.2.3 + v3.3.0
