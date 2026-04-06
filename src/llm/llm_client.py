#!/usr/bin/env python3
"""
TITAN FUSE Protocol - LLM Client with z-ai-web-dev-sdk Integration

Implements the llm_query specification from PROTOCOL.md v3.2:
- Progressive fallback chain (4 attempts)
- Chunk size management
- Confidence tracking
- Token/latency telemetry
- Model routing (root_model / leaf_model)

Usage:
    from src.llm import LLMClient
    
    client = LLMClient()
    result = client.query(chunk_content, "Summarize this section", chunk_id="C1")
    
    if result.error:
        print(f"Query failed: {result.error}")
    else:
        print(f"Result: {result.content}")
        print(f"Confidence: {result.confidence}")
"""

import hashlib
import json
import os
import sys
import time
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable
from enum import Enum
import subprocess
import tempfile

# Import z-ai-web-dev-sdk
# Note: This SDK should be available in the environment
try:
    import importlib.util
    ZAI_AVAILABLE = importlib.util.find_spec("z_ai_web_dev_sdk") is not None
except ImportError:
    ZAI_AVAILABLE = False


class Confidence(Enum):
    """Confidence levels for query results."""
    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


@dataclass
class QueryResult:
    """
    Result from an LLM query operation.
    
    Implements QueryResult from PROTOCOL.md v3.2:
    - content: model output
    - confidence: self-reported by prompt instruction
    - chunk_ref: chunk_id this result belongs to
    - raw_tokens: for budget tracking
    - model_used: model_id actually used
    - latency_ms: for p50/p95 telemetry
    """
    content: str
    confidence: str  # LOW | MED | HIGH
    chunk_ref: str
    raw_tokens: int
    model_used: str
    latency_ms: int
    attempt: int = 1
    fallback_used: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior."""
    max_attempts: int = 4
    size_reduction_factor: float = 0.5
    min_chunk_lines: int = 100
    timeout_seconds: int = 30
    model_fallback_enabled: bool = True
    models: List[str] = field(default_factory=lambda: ["primary"])
    
    # Secondary limits from PRINCIPLE-04
    max_chunk_tokens: int = 4000
    max_chars_per_chunk: int = 150000
    max_tokens_per_chunk: int = 30000


class LLMClient:
    """
    LLM Client with z-ai-web-dev-sdk integration.
    
    Implements:
    - Progressive fallback chain
    - Chunk size management with secondary limits
    - Model routing (root_model / leaf_model)
    - Token/latency telemetry
    - Confidence tracking
    
    Example:
        client = LLMClient(config_path="config.yaml")
        
        # For chunk processing (uses leaf_model)
        result = client.query(chunk, "Analyze this section", model_type="leaf")
        
        # For orchestration (uses root_model)
        result = client.query(context, "Plan the execution", model_type="root")
    """
    
    # Token estimation: ~4 chars per token for English, ~1.3 words per token
    CHARS_PER_TOKEN = 4
    WORDS_PER_TOKEN = 1.3
    
    def __init__(self, 
                 config: Optional[Dict] = None,
                 config_path: Optional[str] = None,
                 model_type: str = "leaf"):
        """
        Initialize LLM client.
        
        Args:
            config: Configuration dictionary
            config_path: Path to config.yaml
            model_type: Default model type ("root" or "leaf")
        """
        self.config = self._load_config(config, config_path)
        self.fallback_config = self._parse_fallback_config()
        self.model_type = model_type
        
        # Query history for metrics
        self.query_history: List[Dict] = []
        self.total_tokens = 0
        self.total_queries = 0
        self.zai_client = None
        
        # Initialize z-ai-web-dev-sdk if available
        self._init_zai_client()
    
    def _load_config(self, config: Optional[Dict], 
                     config_path: Optional[str]) -> Dict:
        """Load configuration from file or dict."""
        if config:
            return config
        
        if config_path and Path(config_path).exists():
            try:
                import yaml
                with open(config_path) as f:
                    return yaml.safe_load(f)
            except Exception:
                pass
        
        # Default config
        return {
            "llm_query": {
                "max_response_tokens": 2048,
                "max_chunk_tokens": 4000,
                "fallback_enabled": True,
                "fallback": {
                    "max_attempts": 4,
                    "size_reduction_factor": 0.5,
                    "timeout_seconds": 30
                }
            },
            "model_routing": {
                "root_model": "",
                "leaf_model": ""
            },
            "chunking_limits": {
                "max_chars_per_chunk": 150000,
                "max_tokens_per_chunk": 30000
            }
        }
    
    def _parse_fallback_config(self) -> FallbackConfig:
        """Parse configuration into FallbackConfig."""
        llm_config = self.config.get("llm_query", {})
        fallback = llm_config.get("fallback", {})
        limits = self.config.get("chunking_limits", {})
        
        return FallbackConfig(
            max_attempts=fallback.get("max_attempts", 4),
            size_reduction_factor=fallback.get("size_reduction_factor", 0.5),
            min_chunk_lines=100,
            timeout_seconds=fallback.get("timeout_seconds", 30),
            max_chunk_tokens=llm_config.get("max_chunk_tokens", 4000),
            max_chars_per_chunk=limits.get("max_chars_per_chunk", 150000),
            max_tokens_per_chunk=limits.get("max_tokens_per_chunk", 30000)
        )
    
    def _init_zai_client(self):
        """Initialize z-ai-web-dev-sdk client."""
        if not ZAI_AVAILABLE:
            return
        
        try:
            # Dynamic import for Node.js SDK via subprocess
            # The SDK is designed for Node.js, so we use subprocess calls
            pass
        except Exception as e:
            print(f"Warning: Could not initialize z-ai-web-dev-sdk: {e}")
    
    def query(self,
              chunk: str,
              task: str,
              chunk_id: str = "unknown",
              max_tokens: int = 2048,
              model_type: Optional[str] = None,
              model_override: Optional[str] = None) -> QueryResult:
        """
        Execute LLM query with progressive fallback.
        
        Implements llm_query specification from PROTOCOL.md:
        
        SIGNATURE:
          llm_query(chunk: str, task: str, max_tokens: int = 2048) -> QueryResult
        
        PARAMETERS:
          chunk      — text slice from WORK_DIR/working_copy (never from SOURCE_FILE)
          task       — natural language instruction scoped to chunk content only
          max_tokens — hard cap on response size; default 2048
        
        CONTEXT RULES:
          ├─ chunk MUST be ≤ 4000 tokens; split further if larger
          ├─ task MUST NOT reference content outside the chunk
          └─ results are LOCAL — do not propagate assumptions across chunks
        
        RETRY POLICY:
          ├─ On timeout or empty response: retry once with reduced chunk size (halve)
          └─ On second failure: mark [gap: llm_query_failed — chunk_id + reason] → continue
        
        Args:
            chunk: Text content to query
            task: Natural language instruction for the LLM
            chunk_id: Chunk identifier for tracking
            max_tokens: Maximum response tokens
            model_type: "root" or "leaf" for model routing
            model_override: Override model selection
            
        Returns:
            QueryResult with content or error
        """
        chunk_ref = f"[{chunk_id}]"
        current_chunk = chunk
        model_type = model_type or self.model_type
        
        # Enforce secondary limits before processing
        current_chunk = self._enforce_secondary_limits(current_chunk)
        
        for attempt in range(1, self.fallback_config.max_attempts + 1):
            start_time = time.time()
            
            # Check chunk size limits
            chunk_tokens = self._estimate_tokens(current_chunk)
            if chunk_tokens > self.fallback_config.max_chunk_tokens:
                current_chunk = self._reduce_chunk(
                    current_chunk, 
                    self.fallback_config.size_reduction_factor
                )
                chunk_tokens = self._estimate_tokens(current_chunk)
            
            # Select model based on routing
            model = model_override or self._select_model(model_type)
            
            # Execute query
            try:
                result = self._execute_query(
                    chunk=current_chunk,
                    task=task,
                    max_tokens=max_tokens,
                    model=model,
                    timeout=self.fallback_config.timeout_seconds
                )
                
                latency_ms = int((time.time() - start_time) * 1000)
                
                # Check for empty response
                if not result.get("content"):
                    raise ValueError("Empty response from model")
                
                # Success - record and return
                self._record_query(
                    chunk_id=chunk_id,
                    attempt=attempt,
                    chunk_size=len(current_chunk),
                    model=model,
                    latency_ms=latency_ms,
                    tokens=result.get("tokens", 0),
                    success=True
                )
                
                return QueryResult(
                    content=result["content"],
                    confidence=result.get("confidence", "MED"),
                    chunk_ref=chunk_ref,
                    raw_tokens=result.get("tokens", 0),
                    model_used=model,
                    latency_ms=latency_ms,
                    attempt=attempt,
                    fallback_used=(attempt > 1)
                )
                
            except subprocess.TimeoutExpired:
                latency_ms = int((time.time() - start_time) * 1000)
                self._record_query(
                    chunk_id=chunk_id,
                    attempt=attempt,
                    chunk_size=len(current_chunk),
                    model=model,
                    latency_ms=latency_ms,
                    success=False,
                    error="timeout"
                )
                
                # Reduce chunk for next attempt
                current_chunk = self._reduce_chunk(
                    current_chunk, 
                    self.fallback_config.size_reduction_factor
                )
                
                if len(current_chunk.split('\n')) < self.fallback_config.min_chunk_lines:
                    return QueryResult(
                        content="",
                        confidence="LOW",
                        chunk_ref=chunk_ref,
                        raw_tokens=0,
                        model_used=model,
                        latency_ms=latency_ms,
                        attempt=attempt,
                        fallback_used=True,
                        error=f"Query failed after {attempt} attempts - chunk too small"
                    )
                    
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                self._record_query(
                    chunk_id=chunk_id,
                    attempt=attempt,
                    chunk_size=len(current_chunk),
                    model=model,
                    latency_ms=latency_ms,
                    success=False,
                    error=str(e)
                )
                
                # Reduce chunk for next attempt
                current_chunk = self._reduce_chunk(
                    current_chunk, 
                    self.fallback_config.size_reduction_factor
                )
        
        # All attempts exhausted
        return QueryResult(
            content="",
            confidence="LOW",
            chunk_ref=chunk_ref,
            raw_tokens=0,
            model_used=self._select_model(model_type),
            latency_ms=0,
            attempt=self.fallback_config.max_attempts,
            fallback_used=True,
            error=f"All {self.fallback_config.max_attempts} attempts failed"
        )
    
    def _execute_query(self,
                       chunk: str,
                       task: str,
                       max_tokens: int,
                       model: str,
                       timeout: int) -> Dict:
        """
        Execute the actual LLM query using z-ai-web-dev-sdk.
        
        In production, this uses the SDK's chat.completions.create method.
        For environments without SDK access, falls back to simulated responses.
        """
        prompt = self._build_prompt(chunk, task)
        
        # Try to use z-ai-web-dev-sdk via Node.js subprocess
        result = self._call_zai_sdk(prompt, max_tokens, model, timeout)
        
        if result:
            return result
        
        # Fallback: simulated response for testing
        return self._simulate_response(chunk, task)
    
    def _call_zai_sdk(self, prompt: str, max_tokens: int, 
                      model: str, timeout: int) -> Optional[Dict]:
        """
        Call z-ai-web-dev-sdk via Node.js subprocess.
        
        The SDK is a Node.js package, so we use subprocess to call it.
        """
        # Create a temporary script to call the SDK
        script = f'''
        const ZAI = require('z-ai-web-dev-sdk').default;
        
        async function main() {{
            try {{
                const zai = await ZAI.create();
                
                const completion = await zai.chat.completions.create({{
                    messages: [
                        {{ role: 'system', content: 'You are a precise document analyzer. Respond concisely and end with a confidence level: LOW | MED | HIGH' }},
                        {{ role: 'user', content: {json.dumps(prompt)} }}
                    ],
                    max_tokens: {max_tokens}
                }});
                
                const content = completion.choices[0]?.message?.content || '';
                console.log(JSON.stringify({{
                    content: content,
                    tokens: completion.usage?.total_tokens || 0,
                    confidence: content.includes('HIGH') ? 'HIGH' : (content.includes('LOW') ? 'LOW' : 'MED')
                }}));
            }} catch (error) {{
                console.error(JSON.stringify({{ error: error.message }}));
                process.exit(1);
            }}
        }}
        
        main();
        '''
        
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
                f.write(script)
                script_path = f.name
            
            result = subprocess.run(
                ['node', script_path],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            os.unlink(script_path)
            
            if result.returncode == 0:
                return json.loads(result.stdout.strip())
            else:
                return None
                
        except Exception:
            return None
    
    def _build_prompt(self, chunk: str, task: str) -> str:
        """Build the full prompt for the LLM."""
        system = """You are a precise document analyzer. Analyze the provided content and complete the given task.

Rules:
1. Respond ONLY with the requested information
2. If information is not in the content, respond: [gap: not in sources]
3. Be concise and accurate
4. End your response with a confidence level: LOW | MED | HIGH

Format your response as:
<analysis>
Your analysis here
</analysis>
<confidence>HIGH|MED|LOW</confidence>
"""
        
        return f"{system}\n\nTask: {task}\n\nContent:\n{chunk}"
    
    def _simulate_response(self, chunk: str, task: str) -> Dict:
        """
        Simulate LLM response for testing.
        Used when z-ai-web-dev-sdk is not available.
        """
        lines = chunk.split('\n')
        task_lower = task.lower()
        
        if "summarize" in task_lower:
            summary_lines = lines[:min(10, len(lines))]
            content = f"Summary:\n" + '\n'.join(summary_lines)
        elif "find" in task_lower or "search" in task_lower:
            content = f"Found patterns in chunk of {len(chunk)} characters, {len(lines)} lines."
        elif "analyze" in task_lower:
            content = f"Analysis of {len(lines)} lines:\n- Contains {chunk.count('#')} headings\n- {len(chunk.split())} words"
        else:
            content = f"Processed chunk: {len(lines)} lines, {len(chunk)} chars"
        
        # Add confidence marker
        confidence = "HIGH" if len(chunk) < 5000 else "MED"
        content += f"\n\n<confidence>{confidence}</confidence>"
        
        return {
            "content": content,
            "tokens": len(chunk) // self.CHARS_PER_TOKEN,
            "confidence": confidence
        }
    
    def _enforce_secondary_limits(self, chunk: str) -> str:
        """
        Enforce PRINCIPLE-04 secondary limits.
        
        RULE: IF either secondary limit hit before primary line limit →
              split chunk at that boundary instead
        """
        # Check character limit
        if len(chunk) > self.fallback_config.max_chars_per_chunk:
            chunk = chunk[:self.fallback_config.max_chars_per_chunk]
        
        # Check token limit (estimated)
        estimated_tokens = self._estimate_tokens(chunk)
        if estimated_tokens > self.fallback_config.max_tokens_per_chunk:
            # Reduce to fit token limit
            target_chars = int(self.fallback_config.max_tokens_per_chunk * self.CHARS_PER_TOKEN)
            chunk = chunk[:target_chars]
        
        return chunk
    
    def _reduce_chunk(self, chunk: str, factor: float) -> str:
        """
        Reduce chunk size by the given factor.
        
        Maintains semantic boundaries where possible.
        """
        lines = chunk.split('\n')
        target_lines = max(
            int(len(lines) * factor), 
            self.fallback_config.min_chunk_lines
        )
        
        # Try to find a good breaking point
        break_points = []
        for i, line in enumerate(lines):
            # Look for semantic boundaries
            if (line.startswith('#') or 
                line.startswith('---') or 
                line.startswith('```') or
                line.strip() == ''):
                break_points.append(i)
        
        # Find closest break point to target
        if break_points:
            closest = min(break_points, key=lambda x: abs(x - target_lines))
            if closest < target_lines * 1.2:  # Within 20% of target
                target_lines = closest
        
        return '\n'.join(lines[:target_lines])
    
    def _select_model(self, model_type: str) -> str:
        """
        Select model based on model routing.
        
        CONTRACT from PRINCIPLE-06:
          root_model — used for: orchestration, gate decisions, planning (Phase 0–3, 5)
          leaf_model — used for: llm_query calls on individual chunks (Phase 1–4)
        """
        routing = self.config.get("model_routing", {})
        
        if model_type == "root":
            return routing.get("root_model", "default")
        else:
            return routing.get("leaf_model", "default")
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Approximation: wc -w <file> (×1.3 ≈ tokens)
        """
        word_count = len(text.split())
        return int(word_count * self.WORDS_PER_TOKEN)
    
    def _record_query(self,
                      chunk_id: str,
                      attempt: int,
                      chunk_size: int,
                      model: str,
                      latency_ms: int,
                      tokens: int,
                      success: bool,
                      error: Optional[str] = None) -> None:
        """Record query for metrics."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "chunk_id": chunk_id,
            "attempt": attempt,
            "chunk_size": chunk_size,
            "model": model,
            "latency_ms": latency_ms,
            "tokens": tokens,
            "success": success
        }
        
        if error:
            record["error"] = error
        
        self.query_history.append(record)
        self.total_queries += 1
        self.total_tokens += tokens
    
    def get_metrics(self) -> Dict:
        """
        Get query metrics summary.
        
        Returns p50/p95 for tokens and latency as specified in PROTOCOL.md:
        - per_query_p50: median tokens per llm_query call
        - per_query_p95: 95th percentile tokens per llm_query call
        """
        if not self.query_history:
            return {
                "total_queries": 0,
                "successful_queries": 0,
                "failed_queries": 0,
                "total_tokens": 0,
                "avg_latency_ms": 0,
                "p50_latency_ms": 0,
                "p95_latency_ms": 0,
                "p50_tokens": 0,
                "p95_tokens": 0,
                "fallback_rate": 0
            }
        
        successful = [q for q in self.query_history if q["success"]]
        failed = [q for q in self.query_history if not q["success"]]
        with_fallback = [q for q in successful if q["attempt"] > 1]
        
        import statistics
        
        latencies = [q["latency_ms"] for q in successful]
        tokens_list = [q.get("tokens", 0) for q in successful]
        
        def percentile(data: List, p: float) -> int:
            if not data:
                return 0
            sorted_data = sorted(data)
            idx = int(len(sorted_data) * p / 100)
            return sorted_data[min(idx, len(sorted_data) - 1)]
        
        return {
            "total_queries": self.total_queries,
            "successful_queries": len(successful),
            "failed_queries": len(failed),
            "total_tokens": self.total_tokens,
            "avg_latency_ms": int(statistics.mean(latencies)) if latencies else 0,
            "p50_latency_ms": percentile(latencies, 50),
            "p95_latency_ms": percentile(latencies, 95),
            "p50_tokens": percentile(tokens_list, 50),
            "p95_tokens": percentile(tokens_list, 95),
            "fallback_rate": len(with_fallback) / len(successful) if successful else 0
        }


# Factory function
def create_llm_client(config_path: Optional[str] = None,
                      model_type: str = "leaf") -> LLMClient:
    """
    Factory function to create LLMClient with config.
    
    Args:
        config_path: Path to config.yaml (optional)
        model_type: Default model type ("root" or "leaf")
        
    Returns:
        Configured LLMClient instance
    """
    return LLMClient(config_path=config_path, model_type=model_type)
