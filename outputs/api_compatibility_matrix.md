# TITAN PROTOCOL v5.0.0 - API COMPATIBILITY MATRIX

## PHASE_0: API Compatibility Analysis (v1.2.0)

**Generated:** 2026-04-09
**Repository Version:** v5.0.0
**Plan Version:** v1.2.0

---

## 1. ProfileRouter vs ProfileDetector Requirements

### Existing Implementation: `src/context/profile_router.py`

| Aspect | Existing | Required (Plan v1.2) | Compatibility |
|--------|----------|---------------------|---------------|
| Class | `ProfileRouter` | `ProfileDetector` (mixin) | ✅ COMPATIBLE |
| Profile Types | 9 execution profiles | 5 user role profiles | ⚠️ DIFFERENT CONCEPTS |
| Detection Method | `detect_profile()` | `detect_with_lexical_analysis()` | ⚠️ EXTEND |
| Lexical Analysis | Not implemented | Required with weighted indicators | ❌ MISSING |
| Pattern Matching | Basic environment checks | Request structure patterns | ⚠️ PARTIAL |
| History Analysis | Not implemented | Session history patterns | ❌ MISSING |
| Cache | Not implemented | LRU cache (1000 entries) | ❌ MISSING |
| EventBus Integration | None | Emit PROFILE_DETECTED | ❌ MISSING |

### v1.2 Decision: MIXIN EXTENSION

**Rationale:** ProfileRouter already contains 29KB of detection logic. Creating a separate ProfileDetector would duplicate code.

**Implementation Strategy:**
```python
# src/context/profile_mixin.py (NEW)
class ProfileDetectionMixin:
    """Mixin extending ProfileRouter with advanced detection capabilities."""
    
    def detect_with_lexical_analysis(self, request: str, context: Optional[Dict] = None) -> ProfileDetectionResult:
        """Detect user role with lexical analysis."""
        pass
    
    def get_lexical_score(self, request: str) -> Dict[str, float]:
        """Calculate lexical scores for each profile."""
        pass
    
    def configure_weights(self, weights: Dict[str, float]) -> None:
        """Configure detection method weights."""
        pass

# Combined usage:
class EnhancedProfileRouter(ProfileRouter, ProfileDetectionMixin):
    """ProfileRouter with extended detection capabilities."""
    pass
```

**User Role Profiles (NEW - Different from Execution Profiles):**
- `designer` - UI/UX, visualization, documentation
- `developer` - Code, debugging, implementation
- `analyst` - Data, validation, reporting
- `devops` - Deployment, monitoring, configuration
- `researcher` - Research, analysis, documentation

---

## 2. RetryExecutor vs RetryExecutorFacade Requirements

### Existing Implementation: `src/policy/retry_logic.py`

| Aspect | Existing | Required (Plan v1.2) | Compatibility |
|--------|----------|---------------------|---------------|
| Class | `RetryExecutor` | `RetryExecutorFacade` | ✅ COMPATIBLE |
| Circuit Breaker | Basic (lines 153-262) | Exposed via facade | ✅ EXISTS |
| Retry Strategies | 5 strategies | Same | ✅ COMPATIBLE |
| Event Emission | None | CIRCUIT_OPENED, etc. | ❌ MISSING |
| Unified Interface | Per-component retry | Single facade | ❌ MISSING |
| Circuit ID Tracking | Single circuit | Multiple named circuits | ⚠️ EXTEND |

### v1.2 Decision: FACADE PATTERN

**Rationale:** Prevents exponential request multiplication from nested retry loops. All adapters and components must use this facade instead of local retry logic.

**Implementation Strategy:**
```python
# src/resilience/retry_executor_facade.py (NEW)
class RetryExecutorFacade:
    """
    Unified facade for retry and circuit breaker operations.
    Wraps existing RetryExecutor with standardized interface.
    """
    
    def execute_with_retry(
        self,
        func: Callable,
        *args,
        max_retries: int = 3,
        backoff_strategy: str = "exponential",
        circuit_id: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Execute function with retry and optional circuit breaker."""
        pass
    
    def get_circuit_state(self, circuit_id: str) -> CircuitState:
        """Get state of named circuit."""
        pass
```

**Usage Contract:**
```python
# CORRECT: Use facade
result = retry_facade.execute_with_retry(
    adapter.on_execute,
    plan,
    max_retries=3,
    circuit_id="skill_graph"
)

# INCORRECT: Local retry loop (forbidden)
for attempt in range(3):  # DO NOT DO THIS
    try:
        result = adapter.on_execute(plan)
    except Exception:
        continue
```

---

## 3. SessionManager vs SessionMemory Requirements

### Existing Implementation: `src/interactive/session.py`

| Aspect | Existing | Required (Plan v1.2) | Compatibility |
|--------|----------|---------------------|---------------|
| Class | `InteractiveSession` | `SessionMemory` | ⚠️ DIFFERENT SCOPE |
| Purpose | Debugging sessions | Cross-request persistence | ❌ DIFFERENT |
| Breakpoints | Yes | No | N/A |
| State Inspection | Yes | Yes | ✅ COMPATIBLE |
| Persistence | Optional | Required (file backend) | ⚠️ PARTIAL |
| Profile Storage | No | Yes | ❌ MISSING |
| History Patterns | Step history | Request history | ⚠️ DIFFERENT |
| Migration | No | With downgrade handler | ❌ MISSING |
| Encryption | No | AES-256-GCM optional | ❌ MISSING |

### v1.2 Decision: CREATE NEW COMPONENT

**Rationale:** InteractiveSession is for debugging (step-by-step execution control). SessionMemory is for cross-request context persistence.

**Implementation Strategy:**
```python
# src/context/session_memory.py (NEW)
class SessionMemory:
    """Cross-request context persistence with migration support."""
    
    def create_session(self, session_id: str) -> Session:
        """Create new session with default state."""
        pass
    
    def update_session(self, session_id: str, updates: Dict) -> bool:
        """Update session with automatic event emission."""
        pass
    
    def migrate_session(self, session_id: str, from_version: str, to_version: str) -> bool:
        """Migrate session schema version."""
        pass
    
    def downgrade_session(self, session_id: str, from_version: str, to_version: str) -> bool:
        """Downgrade session for rollback support."""
        pass
```

---

## 4. IntentHandler vs UniversalRouter Requirements

### Existing Implementation: `src/orchestrator/intent_handler.py`

| Aspect | Existing | Required (Plan v1.2) | Compatibility |
|--------|----------|---------------------|---------------|
| Class | `IntentHandler` | `UniversalRouter` | ⚠️ DIFFERENT SCOPE |
| Purpose | SCOUT pipeline execution | Universal request routing | ❌ DIFFERENT |
| DEVIL Integration | Yes | No (uses skill hints) | N/A |
| Profile Detection | No | Yes | ❌ MISSING |
| Skill Selection | Via ScoutPipeline | Via SkillLibrary | ⚠️ DIFFERENT |
| Chain Composition | No | Yes (ChainComposer) | ❌ MISSING |
| Tool Activation | No | Yes (tool_activation.yaml) | ❌ MISSING |
| Fallback Handling | Pipeline blocking | Multi-level fallback | ⚠️ DIFFERENT |

### v1.2 Decision: CREATE NEW COMPONENT

**Rationale:** IntentHandler is for SCOUT agent pipeline (specific use case). UniversalRouter is for all request types.

**Implementation Strategy:**
```python
# src/orchestrator/universal_router.py (NEW)
class UniversalRouter:
    """Single entry point for all request types."""
    
    def process(self, request: str, context: Optional[Dict] = None) -> RoutingResult:
        """
        Main entry point: Request → Profile Detection → Intent Enrichment → 
        Skill Selection → Chain Composition → Execution → Output Formatting
        """
        pass
    
    def _detect_profile(self, request: str) -> ProfileDetectionResult:
        """Detect user role profile."""
        pass
    
    def _enrich_intent(self, request: str, profile: str) -> EnrichedIntent:
        """Enrich intent with skill hints."""
        pass
    
    def _select_skills(self, intent: str, hints: List[str]) -> List[Skill]:
        """Select skills from library."""
        pass
    
    def _compose_chain(self, skills: List[Skill]) -> SkillChain:
        """Compose execution chain."""
        pass
```

---

## 5. Schema Compatibility Analysis

### Existing Schemas

| Schema | File | Status | v1.2 Updates Needed |
|--------|------|--------|---------------------|
| Validator | `schemas/validator_schema.json` | ✅ EXISTS | Minor: version to 1.2.0 |
| Skill | `schemas/skill.schema.json` | ✅ EXISTS | Minor: version to 1.2.0 |
| Context Bridge | `schemas/context_bridge.schema.json` | ✅ EXISTS | Minor: version to 1.2.0 |
| Event Types | `schemas/event_types.schema.json` | ✅ EXISTS | Minor: version to 1.2.0 |
| **Skill Chain** | `schemas/skill_chain.schema.json` | ❌ MISSING | **CREATE NEW** |

### New Schema Required: skill_chain.schema.json

**Purpose:** Single canonical schema for SkillChain used by UniversalRouter and ChainComposer.

**Structure:**
```json
{
  "chain_id": "chain_xxx",
  "skills": [...],
  "execution_order": [0, 1, 2],
  "parallel_groups": [[0, 1], [2]],
  "context_mapping": {...},
  "gates": ["GATE-02"],
  "fallback_chain": ["skill_b"],
  "estimated_duration_ms": 5000,
  "metadata": {...}
}
```

---

## 6. PluginInterface Compatibility

### Existing Implementation: `src/interfaces/plugin_interface.py`

| Aspect | Existing | Required (Plan v1.2) | Compatibility |
|--------|----------|---------------------|---------------|
| Abstract Class | `PluginInterface` | Same | ✅ COMPATIBLE |
| on_init() | Yes | Yes | ✅ MATCHES |
| on_route() | Returns `RoutingDecision` | Same | ✅ MATCHES |
| on_execute() | Returns `ExecutionResult` | Same | ✅ MATCHES |
| on_error() | Returns `ErrorResult` | Same | ✅ MATCHES |
| on_shutdown() | Yes | Yes | ✅ MATCHES |
| ExecutionResult | Has `success`, `outputs`, `gaps` | Same + `fallback_used` | ⚠️ EXTEND |

### v1.2 Decision: MINOR EXTENSION

**Changes Needed:**
- Add `fallback_used: bool = False` to `ExecutionResult` dataclass
- Already compatible with plan requirements

---

## 7. Integration Points Summary

### Components to Create (NEW)

| Component | Path | Dependencies | Priority |
|-----------|------|--------------|----------|
| SkillChain Schema | `schemas/skill_chain.schema.json` | None | CRITICAL |
| ProfileDetectionMixin | `src/context/profile_mixin.py` | ProfileRouter, EventBus | HIGH |
| IntentEnricher | `src/context/intent_enricher.py` | InputSanitizer, EventBus | HIGH |
| SessionMemory | `src/context/session_memory.py` | EventBus, Storage | HIGH |
| UniversalRouter | `src/orchestrator/universal_router.py` | All above | CRITICAL |
| ChainComposer | `src/orchestrator/chain_composer.py` | SkillChain Schema | HIGH |
| RetryExecutorFacade | `src/resilience/retry_executor_facade.py` | RetryExecutor | HIGH |
| SkillGraphAdapter | `src/skills/adapter.py` | PluginInterface, RetryFacade | HIGH |
| ContextAdapter | `src/skills/context_adapter.py` | ContextBridge Schema | HIGH |
| PolicyAdapter | `src/skills/policy_adapter.py` | PolicyEngine | MEDIUM |
| InputSanitizer | `src/security/input_sanitizer.py` | None | HIGH |
| SessionSecurity | `src/security/session_security.py` | None | MEDIUM |
| DegradationManager | `src/resilience/degradation.py` | EventBus | MEDIUM |

### Components to Extend

| Component | Path | Extension Type | Changes |
|-----------|------|---------------|---------|
| ProfileRouter | `src/context/profile_router.py` | Mixin | Add ProfileDetectionMixin |
| RetryExecutor | `src/policy/retry_logic.py` | Facade | Create RetryExecutorFacade |
| ExecutionResult | `src/interfaces/plugin_interface.py` | Dataclass | Add `fallback_used` field |

### Components to Use As-Is

| Component | Path | Usage |
|-----------|------|-------|
| EventBus | `src/events/event_bus.py` | Event dispatch for all new components |
| SkillLibrary | `src/skills/skill_library.py` | Skill catalog management |
| IntentRouter | `src/policy/intent_router.py` | Intent classification |
| StateManager | `src/state/state_manager.py` | State persistence patterns |
| CheckpointManager | `src/state/checkpoint_manager.py` | Checkpoint patterns |

---

## 8. Configuration Compatibility

### Existing: `config.yaml`
- Already has extensive configuration (28KB)
- Need to add sections for:
  - `skill_graph` configuration
  - `self_awareness` configuration
  - `universal_router` configuration
  - `performance` targets
  - `monitoring` endpoints

### Existing: `config/tool_activation.yaml`
- Already implements ITEM_009
- Contains profile + intent → tool mapping
- Has permission levels, metadata, hot reload

---

## 9. Validation Checklist

- [x] ProfileRouter vs ProfileDetector analyzed
- [x] RetryExecutor vs RetryExecutorFacade analyzed
- [x] SessionManager vs SessionMemory analyzed
- [x] IntentHandler vs UniversalRouter analyzed
- [x] Schema compatibility verified
- [x] PluginInterface compatibility verified
- [x] Integration points documented
- [x] Configuration requirements identified

---

*End of API Compatibility Matrix*
