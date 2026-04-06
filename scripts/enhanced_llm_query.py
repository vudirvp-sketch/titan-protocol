#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Enhanced LLM Query with Fallback Chain
Version: 1.0.0

Implements the 4-attempt progressive fallback chain specified in PROTOCOL.md:
1. Primary attempt with full chunk
2. Retry with halved chunk size
3. Retry with quarter chunk size
4. Final attempt with minimal chunk (500 lines)

This module provides resilient LLM query capabilities for processing
large files in isolated chunk-based operations.
"""

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import subprocess
import tempfile


@dataclass
class QueryResult:
    """Result from an LLM query operation."""
    content: str
    confidence: str  # LOW | MED | HIGH
    chunk_ref: str
    raw_tokens: int
    model_used: str
    latency_ms: int
    attempt: int
    fallback_used: bool
    error: Optional[str] = None


@dataclass
class FallbackConfig:
    """Configuration for fallback behavior."""
    max_attempts: int = 4
    size_reduction_factor: float = 0.5
    min_chunk_size: int = 500
    timeout_seconds: int = 30
    model_fallback_enabled: bool = True
    models: List[str] = field(default_factory=lambda: ["primary", "alternative-1", "alternative-2"])


class EnhancedLLMQuery:
    """
    Enhanced LLM Query with progressive fallback chain.
    
    Usage:
        query = EnhancedLLMQuery(config)
        result = query.execute(chunk_content, task, chunk_id="C1")
        
        if result.error:
            print(f"Query failed after {result.attempt} attempts: {result.error}")
        else:
            print(f"Result: {result.content}")
            print(f"Confidence: {result.confidence}")
    """
    
    # Token estimation: ~4 chars per token for English
    CHARS_PER_TOKEN = 4
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize enhanced LLM query.
        
        Args:
            config: Configuration dict (from config.yaml llm_query section)
        """
        self.config = self._parse_config(config)
        self.query_history: List[Dict] = []
        self.total_tokens = 0
        self.total_queries = 0
    
    def _parse_config(self, config: Optional[Dict]) -> FallbackConfig:
        """Parse configuration into FallbackConfig."""
        if not config:
            return FallbackConfig()
        
        fallback = config.get("fallback", {})
        return FallbackConfig(
            max_attempts=fallback.get("max_attempts", 4),
            size_reduction_factor=fallback.get("size_reduction_factor", 0.5),
            min_chunk_size=fallback.get("min_chunk_size", 500),
            timeout_seconds=fallback.get("timeout_seconds", 30),
            model_fallback_enabled=fallback.get("model_fallback", True),
            models=fallback.get("models", ["primary", "alternative-1", "alternative-2"])
        )
    
    def execute(self,
                chunk: str,
                task: str,
                chunk_id: str = "unknown",
                max_tokens: int = 2048,
                model_override: Optional[str] = None) -> QueryResult:
        """
        Execute LLM query with progressive fallback.
        
        Args:
            chunk: Text content to query
            task: Natural language instruction for the LLM
            chunk_id: Chunk identifier for tracking
            max_tokens: Maximum response tokens
            model_override: Override model selection
            
        Returns:
            QueryResult with content or error
        """
        chunk_ref = f"[{chunk_id}]"
        current_chunk = chunk
        current_size = len(chunk.split('\n'))
        model_index = 0
        
        for attempt in range(1, self.config.max_attempts + 1):
            start_time = time.time()
            
            # Calculate chunk token estimate
            chunk_tokens = len(current_chunk) // self.CHARS_PER_TOKEN
            
            # Check chunk size limits
            if chunk_tokens > 4000:
                # Need to reduce further before query
                current_chunk = self._reduce_chunk(current_chunk, self.config.size_reduction_factor)
                chunk_tokens = len(current_chunk) // self.CHARS_PER_TOKEN
            
            # Select model (with fallback)
            model = model_override or self._select_model(model_index)
            
            # Execute query
            try:
                result = self._execute_query(
                    chunk=current_chunk,
                    task=task,
                    max_tokens=max_tokens,
                    model=model,
                    timeout=self.config.timeout_seconds
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
                # Timeout - reduce chunk and retry
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
                
                # Prepare for next attempt
                current_chunk = self._reduce_chunk(current_chunk, self.config.size_reduction_factor)
                new_size = len(current_chunk.split('\n'))
                
                if new_size < self.config.min_chunk_size:
                    # Check if model fallback is available
                    if self.config.model_fallback_enabled and model_index < len(self.config.models) - 1:
                        model_index += 1
                        current_chunk = chunk  # Reset to original chunk for new model
                    else:
                        # Final fallback failed
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
                # Other error - try fallback
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
                current_chunk = self._reduce_chunk(current_chunk, self.config.size_reduction_factor)
                
                # Check minimum size
                if len(current_chunk.split('\n')) < self.config.min_chunk_size:
                    return QueryResult(
                        content="",
                        confidence="LOW",
                        chunk_ref=chunk_ref,
                        raw_tokens=0,
                        model_used=model,
                        latency_ms=latency_ms,
                        attempt=attempt,
                        fallback_used=True,
                        error=f"Query failed: {str(e)}"
                    )
        
        # All attempts exhausted
        return QueryResult(
            content="",
            confidence="LOW",
            chunk_ref=chunk_ref,
            raw_tokens=0,
            model_used=self._select_model(model_index),
            latency_ms=0,
            attempt=self.config.max_attempts,
            fallback_used=True,
            error=f"All {self.config.max_attempts} attempts failed"
        )
    
    def _execute_query(self,
                       chunk: str,
                       task: str,
                       max_tokens: int,
                       model: str,
                       timeout: int) -> Dict:
        """
        Execute the actual LLM query.
        
        This is a placeholder that should be replaced with actual LLM SDK calls.
        In production, this would use the z-ai-web-dev-sdk or similar.
        """
        # Placeholder implementation
        # In production, this would call:
        # zai.chat.completions.create({
        #     messages: [
        #         {"role": "system", "content": self._build_system_prompt()},
        #         {"role": "user", "content": f"{task}\n\nContent:\n{chunk}"}
        #     ],
        #     max_tokens: max_tokens,
        #     model: model
        # })
        
        # For now, simulate a response
        # This should be replaced with actual LLM integration
        
        prompt = self._build_prompt(chunk, task)
        
        # Simulated response for testing
        # In production, remove this and use actual LLM call
        return {
            "content": self._simulate_response(chunk, task),
            "confidence": "HIGH" if len(chunk) < 2000 else "MED",
            "tokens": len(prompt) // self.CHARS_PER_TOKEN
        }
    
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
    
    def _simulate_response(self, chunk: str, task: str) -> str:
        """
        Simulate LLM response for testing.
        In production, this method should be removed.
        """
        # Simple simulation based on task keywords
        if "summarize" in task.lower():
            lines = chunk.split('\n')[:5]
            return f"Summary of first 5 lines:\n" + '\n'.join(lines)
        elif "find" in task.lower() or "search" in task.lower():
            return f"Found patterns in chunk of {len(chunk)} characters"
        else:
            return f"Processed chunk: {len(chunk.split(chr(10)))} lines, {len(chunk)} chars"
    
    def _reduce_chunk(self, chunk: str, factor: float) -> str:
        """
        Reduce chunk size by the given factor.
        
        Maintains semantic boundaries where possible.
        """
        lines = chunk.split('\n')
        target_lines = max(int(len(lines) * factor), self.config.min_chunk_size)
        
        # Try to find a good breaking point
        break_points = []
        for i, line in enumerate(lines):
            # Look for semantic boundaries
            if line.startswith('#') or line.startswith('---') or line.strip() == '':
                break_points.append(i)
        
        # Find closest break point to target
        if break_points:
            closest = min(break_points, key=lambda x: abs(x - target_lines))
            if closest < target_lines * 1.2:  # Within 20% of target
                target_lines = closest
        
        return '\n'.join(lines[:target_lines])
    
    def _select_model(self, index: int) -> str:
        """Select model based on fallback index."""
        if index < len(self.config.models):
            return self.config.models[index]
        return self.config.models[-1]
    
    def _record_query(self,
                      chunk_id: str,
                      attempt: int,
                      chunk_size: int,
                      model: str,
                      latency_ms: int,
                      success: bool,
                      error: Optional[str] = None) -> None:
        """Record query for metrics and debugging."""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "chunk_id": chunk_id,
            "attempt": attempt,
            "chunk_size": chunk_size,
            "model": model,
            "latency_ms": latency_ms,
            "success": success
        }
        
        if error:
            record["error"] = error
        
        self.query_history.append(record)
        self.total_queries += 1
    
    def get_metrics(self) -> Dict:
        """Get query metrics summary."""
        if not self.query_history:
            return {
                "total_queries": 0,
                "successful_queries": 0,
                "failed_queries": 0,
                "avg_latency_ms": 0,
                "fallback_rate": 0
            }
        
        successful = [q for q in self.query_history if q["success"]]
        failed = [q for q in self.query_history if not q["success"]]
        with_fallback = [q for q in successful if q["attempt"] > 1]
        
        avg_latency = sum(q["latency_ms"] for q in successful) / len(successful) if successful else 0
        
        return {
            "total_queries": self.total_queries,
            "successful_queries": len(successful),
            "failed_queries": len(failed),
            "avg_latency_ms": int(avg_latency),
            "fallback_rate": len(with_fallback) / len(successful) if successful else 0,
            "attempts_distribution": self._get_attempts_distribution()
        }
    
    def _get_attempts_distribution(self) -> Dict[int, int]:
        """Get distribution of attempts needed for success."""
        distribution = {}
        for q in self.query_history:
            if q["success"]:
                attempt = q["attempt"]
                distribution[attempt] = distribution.get(attempt, 0) + 1
        return distribution


def create_enhanced_query(config_path: Optional[str] = None) -> EnhancedLLMQuery:
    """
    Factory function to create EnhancedLLMQuery with config.
    
    Args:
        config_path: Path to config.yaml (optional)
        
    Returns:
        Configured EnhancedLLMQuery instance
    """
    config = {}
    
    if config_path:
        try:
            import yaml
            with open(config_path) as f:
                full_config = yaml.safe_load(f)
                config = full_config.get("llm_query", {})
        except Exception as e:
            print(f"Warning: Could not load config from {config_path}: {e}")
    
    return EnhancedLLMQuery(config)


# CLI interface
def main():
    """CLI entry point for enhanced_llm_query."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="TITAN Enhanced LLM Query with Fallback Chain"
    )
    parser.add_argument("chunk_file", help="File containing chunk content")
    parser.add_argument("task", help="Task description for the LLM")
    parser.add_argument("--chunk-id", default="C1", help="Chunk identifier")
    parser.add_argument("--max-tokens", type=int, default=2048, help="Max response tokens")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    # Read chunk
    with open(args.chunk_file) as f:
        chunk = f.read()
    
    # Create query engine
    query = create_enhanced_query(args.config)
    
    # Execute
    result = query.execute(
        chunk=chunk,
        task=args.task,
        chunk_id=args.chunk_id,
        max_tokens=args.max_tokens
    )
    
    # Output
    if args.json:
        output = {
            "content": result.content,
            "confidence": result.confidence,
            "chunk_ref": result.chunk_ref,
            "tokens": result.raw_tokens,
            "model": result.model_used,
            "latency_ms": result.latency_ms,
            "attempt": result.attempt,
            "fallback_used": result.fallback_used,
            "error": result.error
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"=== Query Result ===")
        print(f"Chunk: {result.chunk_ref}")
        print(f"Attempt: {result.attempt}")
        print(f"Fallback: {'Yes' if result.fallback_used else 'No'}")
        print(f"Confidence: {result.confidence}")
        print(f"Latency: {result.latency_ms}ms")
        print(f"Tokens: {result.raw_tokens}")
        print(f"\n--- Content ---\n")
        print(result.content)
        
        if result.error:
            print(f"\n--- Error ---\n{result.error}")
    
    return 0 if not result.error else 1


if __name__ == "__main__":
    sys.exit(main())
