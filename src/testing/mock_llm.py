"""
TITAN FUSE Protocol - Mock LLM for Testing

Deterministic mock LLM responses for CI/CD and development.
Version: 5.1.0 - Aligned with QueryResult dataclass from enhanced_llm_query.py
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
import hashlib
import json


@dataclass
class MockQueryResult:
    """
    Mock query result aligned with QueryResult from enhanced_llm_query.py.
    
    This dataclass provides all fields expected by the actual QueryResult:
    - content: The response content
    - confidence: LOW | MED | HIGH
    - chunk_ref: Reference to the chunk processed
    - raw_tokens: Number of tokens in response
    - model_used: LLM model identifier
    - latency_ms: Query latency in milliseconds
    - attempt: Which attempt this was (for fallback)
    - fallback_used: Whether fallback was needed
    - error: Optional error message
    """
    content: str
    confidence: str  # LOW | MED | HIGH
    chunk_ref: str
    raw_tokens: int
    model_used: str = "mock-model"
    latency_ms: int = 150
    attempt: int = 1
    fallback_used: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for backward compatibility."""
        return asdict(self)


class MockLLMResponse:
    """
    Deterministic mock LLM responses based on input seed.

    Usage:
        mock = MockLLMResponse(seed=42)
        result = mock.query("Analyze this code", context="...")
        print(result.content)  # Access as dataclass
        print(result.to_dict())  # For backward compatibility
    """

    def __init__(self, seed: int = 42, mode: str = "deterministic"):
        self.seed = seed
        self.mode = mode
        self.response_templates = self._load_templates()
        self.default_model = "mock-model"

    def _load_templates(self) -> Dict:
        """Load response templates for different query types."""
        return {
            "analyze": {
                "pattern": "Analysis of {input_hash}: {findings}",
                "default_findings": ["No issues found", "Code quality: good"]
            },
            "fix": {
                "pattern": "Suggested fix: {fix_description}",
                "default_fixes": ["Refactor for clarity", "Add error handling"]
            },
            "validate": {
                "pattern": "Validation result: {status}",
                "default_status": "PASS"
            }
        }

    def query(self, task: str, context: str = "", max_tokens: int = 2048) -> MockQueryResult:
        """
        Generate deterministic mock response.

        The response is deterministic based on:
        - Seed value
        - Task hash
        - Context hash

        Returns:
            MockQueryResult with all fields aligned with QueryResult
        """
        import time
        start_time = time.time()
        
        # Generate deterministic hash
        combined = f"{self.seed}:{task}:{context}"
        input_hash = hashlib.sha256(combined.encode()).hexdigest()[:8]

        # Determine response type from task
        response_type = self._classify_task(task)
        template = self.response_templates.get(response_type, {})

        # Generate deterministic response
        response = self._generate_response(
            template=template,
            input_hash=input_hash,
            seed=self.seed
        )
        
        # Calculate simulated latency (deterministic based on input)
        latency = 100 + (len(response) % 100)
        
        # Determine confidence based on content length
        confidence = "HIGH" if len(response) < 500 else "MED" if len(response) < 1500 else "LOW"

        return MockQueryResult(
            content=response,
            confidence=confidence,
            chunk_ref=f"[{input_hash}]",
            raw_tokens=min(len(response) // 4, max_tokens),
            model_used=self.default_model,
            latency_ms=latency,
            attempt=1,
            fallback_used=False,
            error=None
        )

    def _classify_task(self, task: str) -> str:
        """Classify task type from natural language."""
        task_lower = task.lower()
        if "analyze" in task_lower or "find" in task_lower:
            return "analyze"
        elif "fix" in task_lower or "repair" in task_lower:
            return "fix"
        elif "validate" in task_lower or "check" in task_lower:
            return "validate"
        return "analyze"

    def _generate_response(self, template: Dict, input_hash: str, seed: int) -> str:
        """Generate deterministic response from template."""
        pattern = template.get("pattern", "Response: {input_hash}")

        # Use seed to select deterministic option
        options = list(template.values())
        if len(options) > 2:
            selected_idx = seed % len(options)
            selected = options[selected_idx]
        else:
            selected = options[-1] if options else "OK"

        if isinstance(selected, list):
            findings_str = ", ".join(str(s) for s in selected[:2])
        else:
            findings_str = str(selected)

        return pattern.format(
            input_hash=input_hash,
            findings=findings_str,
            fix_description="Mock fix applied",
            status="PASS"
        )


class MockLLMProvider:
    """
    Mock provider that wraps MockLLMResponse for Orchestrator integration.
    Compatible with z-ai-web-dev-sdk interface.
    """

    def __init__(self, seed: int = 42):
        self.mock = MockLLMResponse(seed=seed)
        self.call_count = 0
        self.call_log = []

    async def create(self):
        """Async factory for SDK compatibility."""
        return self

    async def chat_completions_create(self, messages: list, **kwargs) -> Dict:
        """Mock completions.create() API."""
        self.call_count += 1

        # Extract task from messages
        task = ""
        context = ""
        for msg in messages:
            if msg.get("role") == "user":
                task = msg.get("content", "")
            elif msg.get("role") == "system":
                context = msg.get("content", "")

        result = self.mock.query(task, context)

        self.call_log.append({
            "call_id": self.call_count,
            "task": task[:100],  # Truncate for logging
            "response_tokens": result.raw_tokens,
            "latency_ms": result.latency_ms
        })

        return {
            "choices": [{
                "message": {
                    "content": result.content,
                    "role": "assistant"
                }
            }],
            "_mock": True,
            "_model_used": result.model_used,
            "_latency_ms": result.latency_ms
        }


class MockZAI:
    """
    Mock ZAI class for testing without actual SDK.
    Mimics z-ai-web-dev-sdk interface.
    """

    def __init__(self, seed: int = 42):
        self.provider = MockLLMProvider(seed=seed)
        self.chat = MockChat(self.provider)
        self.images = MockImages(seed)

    @classmethod
    async def create(cls, seed: int = 42):
        """Factory method for async initialization."""
        return cls(seed=seed)


class MockChat:
    """Mock chat interface."""

    def __init__(self, provider: MockLLMProvider):
        self.provider = provider
        self.completions = MockCompletions(provider)


class MockCompletions:
    """Mock completions interface."""

    def __init__(self, provider: MockLLMProvider):
        self.provider = provider

    async def create(self, messages: list, **kwargs) -> Dict:
        """Create completion."""
        return await self.provider.chat_completions_create(messages, **kwargs)


class MockImages:
    """Mock images interface."""

    def __init__(self, seed: int):
        self.seed = seed
        self.generations = MockGenerations(seed)


class MockGenerations:
    """Mock image generations."""

    def __init__(self, seed: int):
        self.seed = seed

    async def create(self, prompt: str, size: str = "1024x1024", **kwargs) -> Dict:
        """Generate mock image (returns placeholder)."""
        # Return a minimal valid base64 image
        return {
            "data": [{
                "base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "_mock": True,
                "_seed": self.seed
            }]
        }
