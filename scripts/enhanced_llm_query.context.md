---
purpose: "Context and usage guide for enhanced_llm_query.py module"
audience: ["agents", "developers"]
when_to_read: "Before using llm_query for isolated sub-queries"
related_files: ["PROTOCOL.base.md#llm_query-specification", "config.yaml#llm_query"]
stable_sections: ["philosophy", "anti-patterns", "example-invocation"]
emotional_tone: "technical, instructive, cautionary"
---

# enhanced_llm_query.context.md

## Philosophy

This module implements the **progressive fallback chain** for LLM queries on text chunks. It is designed to handle failures gracefully while maintaining protocol integrity.

**Why this exists:**
- Large files are chunked to avoid context overflow
- LLM queries on chunks may fail (timeout, empty response, errors)
- The fallback chain maximizes chances of success
- All failures are logged as gaps with structured context

**Key principle:** Never propagate assumptions across chunks. Results are LOCAL to the chunk.

---

## Core Classes

### `EnhancedLLMQuery`

Main async class with fallback chain:

```
Fallback Strategy:
1. First attempt: Full chunk with primary model
2. Retry 1: Halved chunk size
3. Retry 2: Quarter chunk size
4. Retry 3: Switch to alternative model (if available)
5. Final: Mark as gap with structured context
```

### `SyncEnhancedLLMQuery`

Synchronous wrapper for compatibility with non-async code.

### `QueryResult`

Dataclass containing:
- `content: str` — Model output
- `confidence: Confidence` — LOW | MED | HIGH
- `chunk_ref: str` — Chunk identifier
- `raw_tokens: int` — Token count estimate
- `attempt: int` — Which attempt succeeded
- `fallback_used: bool` — Whether fallback was needed

---

## Anti-Patterns

### ❌ DO NOT:

1. **Query SOURCE_FILE directly**
   ```python
   # WRONG
   result = query(source_file_content, task)
   ```
   Always use content from WORK_DIR/working_copy.

2. **Reference content outside the chunk**
   ```python
   # WRONG
   task = "Summarize this section and the previous one"
   ```
   Task MUST be scoped to chunk content only.

3. **Assume success without checking confidence**
   ```python
   # WRONG
   result = await query.query(chunk, task)
   use_result(result.content)  # May be a gap marker!
   ```
   Always check `result.confidence` and for `[gap:` markers.

4. **Disable model fallback unnecessarily**
   ```python
   # Usually WRONG
   config = FallbackConfig(enable_model_fallback=False)
   ```
   Keep model fallback enabled for resilience.

5. **Set max_attempts too low**
   ```python
   # WRONG for critical chunks
   config = FallbackConfig(max_attempts=1)
   ```
   Use default (4) or higher for critical processing.

---

## Example Invocation

### Async Usage

```python
from enhanced_llm_query import EnhancedLLMQuery, FallbackConfig

# Define your LLM query function
def my_llm_query(chunk: str, task: str, max_tokens: int) -> str:
    # Your LLM API call here
    return llm_api.generate(chunk, task, max_tokens)

# Create query handler with custom config
config = FallbackConfig(
    max_attempts=4,
    initial_chunk_size=4000,
    size_reduction_factor=0.5,
    min_chunk_size=500,
    timeout_seconds=30.0
)

query_handler = EnhancedLLMQuery(my_llm_query, config)

# Execute query
result = await query_handler.query(
    chunk=chunk_from_working_copy,  # NOT from SOURCE_FILE!
    task="Extract all function definitions and their signatures",
    chunk_id="C3",
    max_tokens=2048
)

# Check result
if result.confidence == Confidence.LOW or "[gap:" in result.content:
    print(f"Warning: Low confidence result for {result.chunk_ref}")
    # Mark for human review

print(f"Result: {result.content}")
print(f"Attempt: {result.attempt}")
print(f"Fallback used: {result.fallback_used}")
```

### Sync Usage

```python
from enhanced_llm_query import SyncEnhancedLLMQuery, FallbackConfig

query_handler = SyncEnhancedLLMQuery(my_llm_query, config)

result = query_handler.query(
    chunk=chunk_from_working_copy,
    task="Identify all TODO markers",
    chunk_id="C5"
)
```

---

## Configuration Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_attempts` | 4 | Maximum retry attempts |
| `initial_chunk_size` | 4000 | Initial chunk size in tokens |
| `size_reduction_factor` | 0.5 | Size multiplier on each retry |
| `min_chunk_size` | 500 | Minimum chunk size |
| `timeout_seconds` | 30.0 | Query timeout |
| `enable_model_fallback` | True | Switch models on failure |
| `alternative_models` | ["primary", "alternative-1", "alternative-2"] | Model list |

---

## Gap Handling

When all attempts fail, the module:

1. Creates a gap entry with structured context:
   ```python
   {
       "chunk_id": "C3",
       "task": "Extract function definitions...",
       "reason": "TIMEOUT",
       "timestamp": "2026-04-06T12:00:00",
       "attempts": 4
   }
   ```

2. Returns a QueryResult with gap marker:
   ```python
   content="[gap: llm_query_failed — C3 — TIMEOUT]"
   confidence=Confidence.LOW
   ```

3. Logs the gap for later retrieval:
   ```python
   gaps = query_handler.get_gap_log()
   ```

---

## Statistics

Track query performance:

```python
stats = query_handler.get_stats()
# {
#     "total_queries": 15,
#     "gaps_encountered": 2,
#     "gap_rate": 0.133
# }
```

---

## Connections to Other Protocol Parts

| Component | Connection |
|-----------|------------|
| `PROTOCOL.base.md#llm_query-specification` | Defines the specification this implements |
| `config.yaml#llm_query` | Runtime configuration source |
| `TIER 5 — FAILSAFE` | Handles `llm_query_failure` scenario |
| `INVAR-01` | Results must not fabricate data |
| `Operation Budget` | Token counting for budget tracking |

---

## Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| All attempts fail | Chunk too complex | Reduce chunk size, simplify task |
| Timeout on every attempt | Network/model issue | Increase timeout, check model availability |
| Empty responses | Model confusion | Rephrase task, check chunk content |
| Confidence always LOW | Uncertainty markers in response | Adjust assessment thresholds |

---

**Module Version:** 1.0.0
**Protocol Version:** 3.2.0
**Author:** TITAN FUSE Team
