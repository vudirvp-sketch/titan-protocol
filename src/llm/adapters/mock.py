"""
ITEM-INT-132: Mock Provider Adapter for TITAN Protocol Testing.

This module provides a mock adapter for testing purposes, implementing
the ProviderAdapter interface without making actual API calls.

Features:
- Deterministic responses for testing
- Configurable behavior (delays, errors, etc.)
- Full capability simulation
- Request logging for verification

Author: TITAN FUSE Team
Version: 4.1.0
"""

from typing import Dict, List, Optional, Any, Iterator, Callable
import time
import logging
import json
import hashlib

from .base import (
    ProviderAdapter, AdapterConfig, CompletionResult, StreamChunk,
    AdapterCapability, AdapterError, AdapterConfigError
)


class MockAdapter(ProviderAdapter):
    """
    Mock adapter for testing LLM integration.

    Provides deterministic responses without making actual API calls.
    Useful for unit tests, integration tests, and development.

    Configuration:
        default_model: Model name to simulate
        response_template: Template for responses
        simulate_delay: Whether to simulate API latency
        delay_ms: Simulated delay in milliseconds
        simulate_errors: Whether to simulate random errors
        error_rate: Rate of simulated errors (0.0-1.0)

    Example:
        config = AdapterConfig(
            default_model="mock-gpt-4",
            extra={
                "response_template": "Response: {input}",
                "simulate_delay": True,
                "delay_ms": 100
            }
        )
        adapter = MockAdapter(config)
        result = adapter.complete([{"role": "user", "content": "Hello"}])
        # result.content contains deterministic mock response

    Testing Patterns:
        # Test error handling
        adapter.config.extra["simulate_errors"] = True
        adapter.config.extra["error_rate"] = 1.0  # Always error
        result = adapter.complete([...])
        assert result.error is not None

        # Test latency handling
        adapter.config.extra["simulate_delay"] = True
        adapter.config.extra["delay_ms"] = 1000
        start = time.time()
        result = adapter.complete([...])
        assert (time.time() - start) >= 1.0
    """

    # Known mock models
    KNOWN_MODELS = {
        "mock-gpt-4", "mock-gpt-3.5-turbo",
        "mock-claude-3-opus", "mock-claude-3-sonnet",
        "mock-default"
    }

    DEFAULT_MODEL = "mock-default"

    def __init__(self, config: AdapterConfig):
        """
        Initialize Mock adapter.

        Args:
            config: Adapter configuration
        """
        super().__init__(config)

        # Set default model if not specified
        if config.default_model == "unknown":
            config.default_model = self.DEFAULT_MODEL

        # Mock-specific configuration
        self.response_template = config.extra.get(
            "response_template",
            "[Mock Response for {model}]\n"
            "Input: {input_preview}\n"
            "Tokens: {token_count}\n"
            "<confidence>{confidence}</confidence>"
        )
        self.simulate_delay = config.extra.get("simulate_delay", False)
        self.delay_ms = config.extra.get("delay_ms", 100)
        self.simulate_errors = config.extra.get("simulate_errors", False)
        self.error_rate = config.extra.get("error_rate", 0.0)

        # Request logging for verification
        self.request_log: List[Dict] = []

        # Custom response handler
        self._custom_handler: Optional[Callable] = None

        self._logger.info(
            f"MockAdapter initialized: model={config.default_model}, "
            f"delay={self.delay_ms}ms, error_rate={self.error_rate}"
        )

    @property
    def name(self) -> str:
        """Get adapter name."""
        return "mock"

    @property
    def version(self) -> str:
        """Get adapter version."""
        return "1.0.0"

    def set_custom_handler(self, handler: Callable) -> None:
        """
        Set a custom response handler for advanced testing.

        Args:
            handler: Callable that takes (messages, **kwargs) and returns CompletionResult
        """
        self._custom_handler = handler

    def complete(self, messages: List[Dict[str, str]],
                 **kwargs) -> CompletionResult:
        """
        Execute a mock completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters

        Returns:
            CompletionResult with mock content
        """
        start_time = time.time()

        model = kwargs.get("model", self.config.default_model)
        temperature = kwargs.get("temperature", self.config.temperature)
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        seed = kwargs.get("seed")

        # Log request
        request_record = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "seed": seed,
            "timestamp": time.time()
        }
        self.request_log.append(request_record)

        # Simulate delay if configured
        if self.simulate_delay:
            time.sleep(self.delay_ms / 1000.0)

        # Simulate errors if configured
        if self.simulate_errors:
            import random
            if random.random() < self.error_rate:
                self._record_request(error=True)
                return CompletionResult(
                    content="",
                    model=model,
                    provider=self.name,
                    latency_ms=int((time.time() - start_time) * 1000),
                    error="Simulated error for testing"
                )

        # Use custom handler if set
        if self._custom_handler:
            result = self._custom_handler(messages, **kwargs)
            result.latency_ms = int((time.time() - start_time) * 1000)
            return result

        # Generate deterministic mock response
        result = self._generate_mock_response(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed
        )
        result.latency_ms = int((time.time() - start_time) * 1000)

        return result

    def _generate_mock_response(self, messages: List[Dict[str, str]],
                                model: str, temperature: float,
                                max_tokens: int,
                                seed: Optional[int]) -> CompletionResult:
        """Generate a deterministic mock response."""
        # Get combined input
        input_text = "\n".join(m.get("content", "") for m in messages)
        input_preview = input_text[:100] + "..." if len(input_text) > 100 else input_text

        # Calculate token counts
        prompt_tokens = self.count_tokens(input_text)

        # Generate deterministic confidence based on seed or content
        if seed is not None:
            # Deterministic confidence from seed
            confidence_value = (seed % 3)
            confidence_map = {0: "LOW", 1: "MED", 2: "HIGH"}
            confidence = confidence_map[confidence_value]
        else:
            # Confidence based on input length
            if len(input_text) < 1000:
                confidence = "HIGH"
            elif len(input_text) < 5000:
                confidence = "MED"
            else:
                confidence = "LOW"

        # Build response from template
        response_content = self.response_template.format(
            model=model,
            input_preview=input_preview.replace('\n', ' '),
            token_count=prompt_tokens,
            confidence=confidence,
            temperature=temperature
        )

        # Add deterministic content based on input hash
        if seed is not None:
            hash_input = f"{input_text}:{seed}"
        else:
            hash_input = input_text

        content_hash = hashlib.md5(hash_input.encode()).hexdigest()[:8]
        response_content += f"\n[Hash: {content_hash}]"

        completion_tokens = self.count_tokens(response_content)

        self._record_request(prompt_tokens + completion_tokens)

        return CompletionResult(
            content=response_content,
            model=model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            finish_reason="stop",
            confidence={"HIGH": 0.9, "MED": 0.6, "LOW": 0.3}.get(confidence),
            metadata={
                "mock": True,
                "seed": seed,
                "content_hash": content_hash
            }
        )

    def stream(self, messages: List[Dict[str, str]],
               **kwargs) -> Iterator[StreamChunk]:
        """
        Execute a mock streaming completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters

        Yields:
            StreamChunk objects
        """
        model = kwargs.get("model", self.config.default_model)

        # Generate full response first
        result = self._generate_mock_response(
            messages=messages,
            model=model,
            temperature=kwargs.get("temperature", self.config.temperature),
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            seed=kwargs.get("seed")
        )

        # Stream it word by word
        words = result.content.split()
        full_content = ""

        for i, word in enumerate(words):
            if self.simulate_delay:
                time.sleep(self.delay_ms / 1000.0 / len(words))

            full_content += word + " "
            yield StreamChunk(
                content=full_content.strip(),
                delta=word + " ",
                is_final=(i == len(words) - 1),
                finish_reason="stop" if i == len(words) - 1 else None
            )

    def count_tokens(self, text: str) -> int:
        """
        Count tokens (mock implementation).

        Args:
            text: Text to count tokens for

        Returns:
            int: Estimated token count
        """
        # Simple estimation: ~4 chars per token
        return len(text) // 4

    def validate_config(self, config: Dict) -> bool:
        """
        Validate mock configuration.

        Args:
            config: Configuration dictionary

        Returns:
            bool: Always True for mock adapter
        """
        # Mock adapter accepts any configuration
        # But we can validate error_rate
        error_rate = config.get("extra", {}).get("error_rate", 0.0)
        if not 0 <= error_rate <= 1:
            raise AdapterConfigError(
                f"error_rate must be between 0 and 1, got {error_rate}"
            )

        return True

    def get_capabilities(self) -> List[AdapterCapability]:
        """
        Get mock adapter capabilities.

        Returns:
            List of all capabilities (mock supports everything)
        """
        return [
            AdapterCapability.STREAMING,
            AdapterCapability.FUNCTION_CALLING,
            AdapterCapability.VISION,
            AdapterCapability.SEED_PARAMETER,
            AdapterCapability.TEMPERATURE_CONTROL,
            AdapterCapability.TOKEN_COUNTING,
            AdapterCapability.SYSTEM_PROMPT,
            AdapterCapability.MULTI_MODAL
        ]

    def get_request_log(self) -> List[Dict]:
        """
        Get the log of all requests made to this adapter.

        Returns:
            List of request records
        """
        return self.request_log.copy()

    def clear_request_log(self) -> None:
        """Clear the request log."""
        self.request_log.clear()

    def get_last_request(self) -> Optional[Dict]:
        """
        Get the last request made to this adapter.

        Returns:
            Last request record or None if no requests
        """
        return self.request_log[-1] if self.request_log else None

    def get_available_models(self) -> List[str]:
        """
        Get list of known mock models.

        Returns:
            List of model names
        """
        return list(self.KNOWN_MODELS)


def create_mock_adapter(model: str = "mock-default",
                        response_template: Optional[str] = None,
                        **extra_config) -> MockAdapter:
    """
    Factory function to create a MockAdapter with common configurations.

    Args:
        model: Model name to simulate
        response_template: Optional custom response template
        **extra_config: Additional configuration options

    Returns:
        Configured MockAdapter instance
    """
    extra = extra_config.copy()
    if response_template:
        extra["response_template"] = response_template

    config = AdapterConfig(
        default_model=model,
        extra=extra
    )

    return MockAdapter(config)
