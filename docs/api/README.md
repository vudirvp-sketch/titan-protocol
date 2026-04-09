# TITAN Protocol v1.2.0 API Documentation

## Overview

TITAN Protocol is a universal self-configuring tool that auto-detects user profiles and dynamically activates relevant skills based on intent. This documentation covers the main APIs and integration points.

---

## Core Components

### 1. Universal Router

The Universal Router is the single entry point for all request types.

#### Location
`src/orchestrator/universal_router.py`

#### Class: `UniversalRouter`

```python
class UniversalRouter:
    def __init__(
        self,
        config: Dict,
        event_bus: EventBus,
        skill_library: SkillLibrary,
        intent_router: IntentRouter,
        retry_facade: RetryExecutorFacade,
    )
    
    def process(self, request: str, context: Optional[Dict] = None) -> RoutingResult:
        """Process a request and return routing result."""
        pass
```

#### Data Structures

```python
@dataclass
class RoutingResult:
    request_id: str
    profile_type: str
    intent: str
    selected_skills: List[str]
    execution_chain: SkillChain
    output: FormattedOutput
    metrics: Dict[str, Any]
    timestamp: str
    fallback_used: bool
```

---

### 2. Profile Detection

#### Location
`src/context/profile_mixin.py`

#### Class: `ProfileDetectionMixin`

```python
class ProfileDetectionMixin:
    def detect_with_lexical_analysis(
        self, 
        request: str, 
        context: Optional[Dict] = None
    ) -> ProfileDetectionResult:
        """Detect user profile from request text."""
        pass
    
    def configure_weights(self, weights: Dict[str, float]) -> None:
        """Configure detection method weights."""
        pass
    
    def clear_cache(self) -> None:
        """Clear detection cache."""
        pass
```

#### Supported Profiles

| Profile | Keywords |
|---------|----------|
| designer | design, ui, ux, visual, layout, color |
| developer | refactor, debug, implement, code, test |
| analyst | analyze, report, metric, data, insight |
| devops | deploy, server, config, scale, monitor |
| researcher | research, explore, hypothesis, paper |

#### Data Structures

```python
@dataclass
class ProfileDetectionResult:
    profile_type: str
    confidence: float
    detection_method: str
    scores: Dict[str, float]
    indicators_matched: List[str]
    timestamp: str
    fallback_used: bool
```

---

### 3. Intent Enrichment

#### Location
`src/context/intent_enricher.py`

#### Class: `IntentEnricher`

```python
class IntentEnricher:
    def __init__(
        self,
        config: Dict,
        intent_router: IntentRouter,
        profile_router: EnhancedProfileRouter,
        event_bus: EventBus,
        retry_facade: RetryExecutorFacade,
    )
    
    def enrich(
        self, 
        raw_request: str, 
        context: Optional[Dict] = None
    ) -> EnrichedIntent:
        """Enrich raw request with intent and skill hints."""
        pass
```

#### Pipeline Stages

1. **sanitize** - Security sanitization
2. **normalize** - Text normalization
3. **classify** - Intent classification
4. **detect_profile** - Profile detection
5. **enrich** - Add skill hints and gates
6. **emit** - Emit EVENT_CONTEXT_READY

---

### 4. Session Memory

#### Location
`src/context/session_memory.py`

#### Class: `SessionMemory`

```python
class SessionMemory:
    def create_session(self, session_id: str) -> Session:
        """Create a new session."""
        pass
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        pass
    
    def update_session(self, session_id: str, updates: Dict) -> bool:
        """Update session data."""
        pass
    
    def add_request(
        self, 
        session_id: str, 
        request: str, 
        result: Dict
    ) -> None:
        """Add request to session history."""
        pass
    
    def migrate_session(
        self, 
        session_id: str, 
        from_version: str, 
        to_version: str
    ) -> bool:
        """Migrate session to new schema version."""
        pass
    
    def downgrade_session(
        self, 
        session_id: str, 
        from_version: str, 
        to_version: str
    ) -> bool:
        """Downgrade session schema (for rollback)."""
        pass
```

---

### 5. Chain Composer

#### Location
`src/orchestrator/chain_composer.py`

#### Class: `ChainComposer`

```python
class ChainComposer:
    def compose(
        self, 
        skills: List[Skill], 
        context: Dict
    ) -> SkillChain:
        """Compose skill chain from selected skills."""
        pass
    
    def optimize_chain(self, chain: SkillChain) -> SkillChain:
        """Optimize chain for parallel execution."""
        pass
    
    def validate_chain(self, chain: SkillChain) -> ValidationResult:
        """Validate chain for cycles and dependencies."""
        pass
    
    def detect_cycles(self, skills: List[Skill]) -> List[Dict]:
        """Detect cyclic dependencies in skills."""
        pass
```

---

## Resilience Components

### 6. Circuit Breaker

#### Location
`src/resilience/circuit_breaker.py`

#### Class: `CircuitBreaker`

```python
class CircuitBreaker:
    def __init__(
        self,
        circuit_id: str,
        config: Optional[CircuitBreakerConfig] = None,
        event_bus: Optional[EventBus] = None,
    )
    
    def execute(
        self, 
        operation: Callable[[], Any],
        on_failure: Optional[Callable[[Exception], None]] = None,
    ) -> Any:
        """Execute operation with circuit breaker protection."""
        pass
    
    def reset(self) -> None:
        """Reset circuit to CLOSED state."""
        pass
    
    def force_open(self) -> None:
        """Force circuit to OPEN state."""
        pass
    
    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        pass
```

#### States

| State | Description |
|-------|-------------|
| CLOSED | Normal operation, requests pass through |
| OPEN | Circuit tripped, requests fail fast |
| HALF_OPEN | Testing state, limited requests allowed |

---

### 7. Degradation Manager

#### Location
`src/resilience/degradation.py`

#### Class: `DegradationManager`

```python
class DegradationManager:
    def get_level(self) -> DegradationLevel:
        """Get current degradation level."""
        pass
    
    def set_level(self, level: DegradationLevel, reason: str = "") -> None:
        """Set degradation level."""
        pass
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if feature is enabled."""
        pass
    
    def disable_feature(
        self, 
        feature_name: str, 
        reason: str = ""
    ) -> bool:
        """Disable a feature."""
        pass
    
    def get_profile_detection_weights(self) -> Dict[str, float]:
        """Get weights adjusted for current level."""
        pass
    
    def get_fallback_chain(self) -> List[str]:
        """Get fallback chain for current level."""
        pass
```

#### Degradation Levels

| Level | Features Available |
|-------|-------------------|
| FULL | All features |
| REDUCED | skill_graph, profile_detection, intent_enrichment |
| MINIMAL | direct_prompt only |

---

### 8. Retry Executor Facade

#### Location
`src/resilience/retry_executor_facade.py`

#### Class: `RetryExecutorFacade`

```python
class RetryExecutorFacade:
    def execute_with_retry(
        self,
        func: Callable,
        *args,
        max_retries: int = 3,
        backoff_strategy: str = "exponential",
        initial_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        jitter: bool = True,
        circuit_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Execute function with retry and optional circuit breaker."""
        pass
    
    def get_circuit_state(self, circuit_id: str) -> CircuitState:
        """Get state of named circuit."""
        pass
    
    def reset_circuit(self, circuit_id: str) -> None:
        """Reset named circuit."""
        pass
    
    def get_retry_stats(self) -> Dict[str, Any]:
        """Get retry statistics."""
        pass
```

---

## Security Components

### 9. Input Sanitizer

#### Location
`src/security/input_sanitizer.py`

#### Class: `InputSanitizer`

```python
class InputSanitizer:
    def sanitize(self, text: str) -> SanitizationResult:
        """Sanitize input text for security."""
        pass
    
    def detect_injection(self, text: str) -> InjectionResult:
        """Detect prompt injection attempts."""
        pass
    
    def escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        pass
    
    def remove_control_chars(self, text: str) -> str:
        """Remove control characters."""
        pass
    
    def detect_unicode_homoglyphs(self, text: str) -> List[tuple]:
        """Detect unicode homoglyphs."""
        pass
```

#### Sanitization Actions

| Action | Description |
|--------|-------------|
| REJECT | Reject request entirely |
| DROP | Silently drop dangerous content |
| ISOLATE | Isolate request in sandbox |
| SANITIZE_AND_WARN | Sanitize and log warning |

---

### 10. Session Security

#### Location
`src/security/session_security.py`

#### Class: `SessionSecurity`

```python
class SessionSecurity:
    def generate_session_id(self) -> str:
        """Generate secure session ID."""
        pass
    
    def validate_session_id(self, session_id: str) -> bool:
        """Validate session ID format."""
        pass
    
    def encrypt_session_data(self, data: Dict[str, Any]) -> str:
        """Encrypt session data (AES-256-GCM)."""
        pass
    
    def decrypt_session_data(self, encrypted_data: str) -> Dict[str, Any]:
        """Decrypt session data."""
        pass
    
    def rotate_keys(self) -> bool:
        """Rotate encryption keys."""
        pass
    
    def create_session_hash(
        self,
        session_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """Create session binding hash."""
        pass
```

---

## Event Types

### Event Bus Integration

All components integrate with EventBus. Key events:

| Event Type | Source | Description |
|------------|--------|-------------|
| PROFILE_DETECTED | ProfileRouter | Profile detected from request |
| EVENT_CONTEXT_READY | IntentEnricher | Context ready for skill execution |
| SKILL_CHAIN_COMPOSED | ChainComposer | Skill chain composed |
| CIRCUIT_OPENED | CircuitBreaker | Circuit breaker opened |
| CIRCUIT_CLOSED | CircuitBreaker | Circuit breaker closed |
| CIRCUIT_HALF_OPEN | CircuitBreaker | Circuit breaker half-open |
| DEGRADATION_LEVEL_CHANGED | DegradationManager | Degradation level changed |
| SECURITY_ALERT | InputSanitizer | Security threat detected |
| SESSION_SECURITY_ALERT | SessionSecurity | Session security violation |

---

## Configuration

### Main Configuration File

Location: `config.yaml`

```yaml
# Self-Awareness Configuration
self_awareness:
  enabled: true
  profile_detection:
    enabled: true
    min_confidence: 0.6
    lexical_weight: 0.4
    pattern_weight: 0.3
    history_weight: 0.2
    explicit_weight: 0.1

  intent_enrichment:
    enabled: true
    emit_context_ready: true
    input_sanitization: true
    max_request_length: 10000

  session_memory:
    enabled: true
    backend: "file"
    path: ".titan/sessions/"
    ttl_seconds: 86400

# Universal Router Configuration
universal_router:
  enabled: true
  default_profile: "developer"
  fallback_profile: "developer"
  timeout_ms: 2000

# Performance Configuration
performance:
  profile_detection_timeout_ms: 500
  intent_enrichment_timeout_ms: 1000
  session_memory_timeout_ms: 200
  end_to_end_routing_timeout_ms: 2000

# Monitoring Configuration
monitoring:
  metrics_enabled: true
  metrics_format: prometheus
  metrics_endpoint: /metrics
  metrics_port_range: [9090, 9095]
```

---

## Metrics

### Prometheus Metrics

| Metric Name | Type | Description |
|-------------|------|-------------|
| titan_profile_detection_latency_ms | histogram | Profile detection latency |
| titan_profile_detection_total | counter | Total profile detections |
| titan_intent_enrichment_latency_ms | histogram | Intent enrichment latency |
| titan_session_count | gauge | Active session count |
| titan_circuit_state | gauge | Circuit breaker state |
| titan_circuit_transitions_total | counter | Circuit state transitions |
| titan_fallback_triggered_total | counter | Fallback triggers |
| titan_retry_attempts_total | counter | Retry attempts |
| titan_retry_exhausted_total | counter | Retry exhaustions |
| titan_security_alerts_total | counter | Security alerts |

---

## Error Handling

### Error Hierarchy

```
TITANError (base)
├── ProfileDetectionError
├── IntentEnrichmentError
├── SessionMemoryError
├── CircuitBreakerError
├── DegradationError
├── SanitizationError
└── SessionSecurityError
```

### Fallback Chain

1. skill_graph_composition
2. intent_router_only
3. direct_prompt

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.2.0 | 2026-04-10 | Added resilience and security layers |
| 1.1.0 | 2026-04-09 | Added session memory and chain composer |
| 1.0.0 | 2026-04-08 | Initial release with core components |
