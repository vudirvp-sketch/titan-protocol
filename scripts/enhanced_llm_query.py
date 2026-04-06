"""
TITAN FUSE Protocol - Enhanced llm_query with Fallback Chain
Version: 1.0.0
Purpose: Implements progressive fallback strategy for LLM queries
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime, timezone


class Confidence(Enum):
    LOW = "LOW"
    MED = "MED"
    HIGH = "HIGH"


class FallbackReason(Enum):
    TIMEOUT = "TIMEOUT"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    ERROR = "ERROR"
    TOKEN_LIMIT = "TOKEN_LIMIT"
    QUALITY_CHECK_FAILED = "QUALITY_CHECK_FAILED"


@dataclass
class QueryResult:
    """Result from an LLM query."""
    content: str
    confidence: Confidence
    chunk_ref: str
    raw_tokens: int
    attempt: int
    fallback_used: bool
    fallback_reason: Optional[FallbackReason] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FallbackConfig:
    """Configuration for fallback chain."""
    max_attempts: int = 4
    initial_chunk_size: int = 4000
    size_reduction_factor: float = 0.5
    min_chunk_size: int = 500
    timeout_seconds: float = 30.0
    enable_model_fallback: bool = True
    alternative_models: List[str] = field(default_factory=lambda: [
        "primary",  # TODO: Replace with actual model identifier
        "alternative-1",  # TODO: Replace with actual model identifier
        "alternative-2"  # TODO: Replace with actual model identifier
    ])
    # WARNING: Default model names are placeholders.
    # Set alternative_models to actual model identifiers before production use,
    # or load from config.yaml


class EnhancedLLMQuery:
    """
    Enhanced llm_query with progressive fallback chain.

    Fallback Strategy:
    1. First attempt: Full chunk with primary model
    2. Retry 1: Halved chunk size
    3. Retry 2: Quarter chunk size
    4. Retry 3: Switch to alternative model (if available)
    5. Final: Mark as gap with structured context
    """

    def __init__(
        self,
        query_fn: Callable[[str, str, int], str],
        config: Optional[FallbackConfig] = None
    ):
        """
        Initialize the enhanced query handler.

        Args:
            query_fn: Function that performs the actual LLM query.
                     Signature: (chunk: str, task: str, max_tokens: int) -> str
            config: Fallback configuration
        """
        self.query_fn = query_fn
        self.config = config or FallbackConfig()
        self._attempt_count = 0
        self._gap_log: List[Dict[str, Any]] = []

    def _calculate_chunk_size(self, attempt: int) -> int:
        """Calculate chunk size for given attempt number."""
        size = self.config.initial_chunk_size
        for _ in range(attempt):
            size = int(size * self.config.size_reduction_factor)
        return max(size, self.config.min_chunk_size)

    def _split_chunk(self, chunk: str, target_size: int) -> List[str]:
        """Split chunk into smaller pieces if needed."""
        if len(chunk) <= target_size * 4:  # Rough token estimate
            return [chunk]

        # Split by paragraphs first
        paragraphs = chunk.split('\n\n')
        chunks = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) < target_size * 4:
                current += para + "\n\n"
            else:
                if current:
                    chunks.append(current.strip())
                current = para + "\n\n"

        if current:
            chunks.append(current.strip())

        return chunks

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count from text."""
        # Rough estimation: ~4 characters per token
        return len(text) // 4

    def _select_model(self, attempt: int) -> str:
        """Select model based on attempt number."""
        if not self.config.enable_model_fallback:
            return "primary"

        model_index = min(
            attempt // 2,  # Switch model every 2 attempts
            len(self.config.alternative_models) - 1
        )
        return self.config.alternative_models[model_index]

    async def _execute_query(
        self,
        chunk: str,
        task: str,
        max_tokens: int,
        model: str
    ) -> tuple[Optional[str], Optional[FallbackReason]]:
        """Execute a single query attempt with timeout handling."""
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self.query_fn, chunk, task, max_tokens),
                timeout=self.config.timeout_seconds
            )

            if not result or not result.strip():
                return None, FallbackReason.EMPTY_RESPONSE

            return result, None

        except asyncio.TimeoutError:
            return None, FallbackReason.TIMEOUT
        except Exception as e:
            print(f"Query error: {e}")
            return None, FallbackReason.ERROR

    def _assess_confidence(self, content: str, chunk: str) -> Confidence:
        """Assess confidence level of the result."""
        # Check for gap markers
        if "[gap:" in content.lower():
            return Confidence.LOW

        # Check for uncertainty markers
        uncertainty_markers = ["unclear", "cannot determine", "not specified", "unknown"]
        if any(marker in content.lower() for marker in uncertainty_markers):
            return Confidence.MED

        # Check if response addresses the task
        if len(content) < 50:
            return Confidence.LOW

        return Confidence.HIGH

    async def query(
        self,
        chunk: str,
        task: str,
        chunk_id: str = "C1",
        max_tokens: int = 2048
    ) -> QueryResult:
        """
        Execute query with fallback chain.

        Args:
            chunk: Text chunk to query (should be from WORK_DIR, not SOURCE_FILE)
            task: Natural language instruction scoped to chunk content
            chunk_id: Identifier for the chunk (e.g., "C1", "C2")
            max_tokens: Hard cap on response size

        Returns:
            QueryResult with content, confidence, and metadata
        """
        self._attempt_count += 1
        current_chunk = chunk
        attempt = 0
        last_reason = None

        while attempt < self.config.max_attempts:
            attempt += 1
            chunk_size = self._calculate_chunk_size(attempt - 1)
            model = self._select_model(attempt - 1)

            # Split chunk if needed
            if self._estimate_tokens(current_chunk) > chunk_size:
                split_chunks = self._split_chunk(current_chunk, chunk_size)
                # Use first chunk for now (could be enhanced to handle multiple)
                current_chunk = split_chunks[0] if split_chunks else current_chunk

            print(f"[llm_query] Attempt {attempt}/{self.config.max_attempts} "
                  f"(chunk_size: {chunk_size}, model: {model})")

            result, reason = await self._execute_query(
                current_chunk, task, max_tokens, model
            )

            if result is not None:
                confidence = self._assess_confidence(result, current_chunk)
                return QueryResult(
                    content=result,
                    confidence=confidence,
                    chunk_ref=chunk_id,
                    raw_tokens=self._estimate_tokens(result),
                    attempt=attempt,
                    fallback_used=(attempt > 1),
                    fallback_reason=last_reason
                )

            last_reason = reason
            print(f"[llm_query] Attempt {attempt} failed: {reason}")

            # If empty response, try with smaller chunk
            if reason == FallbackReason.EMPTY_RESPONSE:
                continue

            # If timeout, definitely reduce size
            if reason == FallbackReason.TIMEOUT:
                continue

        # All attempts failed - mark as gap
        gap_entry = {
            "chunk_id": chunk_id,
            "task": task[:200],  # Truncate for storage
            "reason": last_reason.value if last_reason else "UNKNOWN",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempts": attempt
        }
        self._gap_log.append(gap_entry)

        return QueryResult(
            content=f"[gap: llm_query_failed — {chunk_id} — {last_reason.value if last_reason else 'unknown reason'}]",
            confidence=Confidence.LOW,
            chunk_ref=chunk_id,
            raw_tokens=0,
            attempt=attempt,
            fallback_used=True,
            fallback_reason=last_reason
        )

    def get_gap_log(self) -> List[Dict[str, Any]]:
        """Get log of all gaps encountered."""
        return self._gap_log.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get query statistics."""
        return {
            "total_queries": self._attempt_count,
            "gaps_encountered": len(self._gap_log),
            "gap_rate": len(self._gap_log) / max(self._attempt_count, 1)
        }


# Synchronous wrapper for compatibility
class SyncEnhancedLLMQuery:
    """Synchronous wrapper for EnhancedLLMQuery."""

    def __init__(
        self,
        query_fn: Callable[[str, str, int], str],
        config: Optional[FallbackConfig] = None
    ):
        self._async_query = EnhancedLLMQuery(query_fn, config)

    def query(
        self,
        chunk: str,
        task: str,
        chunk_id: str = "C1",
        max_tokens: int = 2048
    ) -> QueryResult:
        """Synchronous query method."""
        return asyncio.run(
            self._async_query.query(chunk, task, chunk_id, max_tokens)
        )

    def get_gap_log(self) -> List[Dict[str, Any]]:
        return self._async_query.get_gap_log()

    def get_stats(self) -> Dict[str, Any]:
        return self._async_query.get_stats()


# Example usage
if __name__ == "__main__":
    # Mock query function for demonstration
    def mock_query(chunk: str, task: str, max_tokens: int) -> str:
        """Simulate LLM query with occasional failures."""
        import random
        if random.random() < 0.3:  # 30% failure rate
            raise TimeoutError("Simulated timeout")
        return f"Processed chunk of {len(chunk)} chars. Task: {task[:50]}..."

    async def demo():
        query_handler = EnhancedLLMQuery(
            mock_query,
            FallbackConfig(max_attempts=3, timeout_seconds=5.0)
        )

        sample_chunk = "This is a sample chunk of text. " * 100

        result = await query_handler.query(
            chunk=sample_chunk,
            task="Summarize the main points",
            chunk_id="C1"
        )

        print(f"\nResult: {result.content[:100]}...")
        print(f"Confidence: {result.confidence.value}")
        print(f"Attempt: {result.attempt}")
        print(f"Fallback used: {result.fallback_used}")
        print(f"\nStats: {query_handler.get_stats()}")

    asyncio.run(demo())
