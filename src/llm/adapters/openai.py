"""
ITEM-INT-132: OpenAI Provider Adapter for TITAN Protocol.

This module provides an adapter for OpenAI's GPT models, implementing
the ProviderAdapter interface for seamless integration with the
ProviderAdapterRegistry.

Supported Models:
- gpt-4, gpt-4-turbo, gpt-4o
- gpt-3.5-turbo
- o1-preview, o1-mini

Capabilities:
- Streaming responses
- Function calling
- Vision (gpt-4-vision, gpt-4o)
- Seed parameter for determinism
- Token counting (tiktoken)

Author: TITAN FUSE Team
Version: 4.1.0
"""

from typing import Dict, List, Optional, Any, Iterator
import time
import logging
import os

from .base import (
    ProviderAdapter, AdapterConfig, CompletionResult, StreamChunk,
    AdapterCapability, AdapterError, AdapterConfigError, AdapterRequestError
)


class OpenAIAdapter(ProviderAdapter):
    """
    Adapter for OpenAI GPT models.

    Implements the ProviderAdapter interface for OpenAI's API.

    Configuration:
        api_key: OpenAI API key (or OPENAI_API_KEY env var)
        api_base: Custom API base URL (optional)
        default_model: Default model (e.g., "gpt-4", "gpt-3.5-turbo")
        max_tokens: Maximum tokens per request
        temperature: Sampling temperature (0.0-2.0)

    Example:
        config = AdapterConfig(
            api_key="sk-...",
            default_model="gpt-4",
            max_tokens=4096,
            temperature=0.7
        )
        adapter = OpenAIAdapter(config)
        result = adapter.complete([
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"}
        ])
    """

    # Known OpenAI model names
    KNOWN_MODELS = {
        "gpt-4", "gpt-4-turbo", "gpt-4-turbo-preview", "gpt-4o", "gpt-4o-mini",
        "gpt-3.5-turbo", "gpt-3.5-turbo-16k",
        "o1-preview", "o1-mini"
    }

    # Default models for different use cases
    DEFAULT_MODEL = "gpt-4"
    CHEAP_MODEL = "gpt-3.5-turbo"

    def __init__(self, config: AdapterConfig):
        """
        Initialize OpenAI adapter.

        Args:
            config: Adapter configuration
        """
        super().__init__(config)

        # Use environment variable if API key not in config
        self._api_key = config.api_key or os.environ.get("OPENAI_API_KEY")
        self._api_base = config.api_base or os.environ.get("OPENAI_API_BASE")

        # Set default model if not specified
        if config.default_model == "unknown":
            config.default_model = self.DEFAULT_MODEL

        self._client = None
        self._tiktoken_available = False

        # Check for optional dependencies
        self._check_dependencies()

        self._logger.info(
            f"OpenAIAdapter initialized: model={config.default_model}, "
            f"api_key_set={self._api_key is not None}, "
            f"tiktoken={self._tiktoken_available}"
        )

    def _check_dependencies(self) -> None:
        """Check for optional dependencies."""
        try:
            import openai
            self._openai_available = True
        except ImportError:
            self._openai_available = False
            self._logger.warning(
                "openai package not installed. Using simulated responses."
            )

        try:
            import tiktoken
            self._tiktoken_available = True
            self._encoding = None
        except ImportError:
            self._tiktoken_available = False
            self._logger.debug(
                "tiktoken not installed. Using estimated token counts."
            )

    @property
    def name(self) -> str:
        """Get adapter name."""
        return "openai"

    @property
    def version(self) -> str:
        """Get adapter version."""
        return "1.0.0"

    def _get_client(self):
        """Get or create OpenAI client."""
        if self._client is None and self._openai_available:
            import openai
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=self._api_base
            )
        return self._client

    def complete(self, messages: List[Dict[str, str]],
                 **kwargs) -> CompletionResult:
        """
        Execute a completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters:
                - model: Model override
                - temperature: Temperature override
                - max_tokens: Max tokens override
                - seed: Seed for deterministic output
                - functions: Function definitions for function calling

        Returns:
            CompletionResult with the generated content
        """
        start_time = time.time()

        model = kwargs.get("model", self.config.default_model)
        temperature = kwargs.get("temperature", self.config.temperature)
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        seed = kwargs.get("seed")
        functions = kwargs.get("functions")

        try:
            client = self._get_client()

            if client is not None:
                # Real API call
                params = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }

                if seed is not None:
                    params["seed"] = seed

                if functions:
                    params["functions"] = functions

                response = client.chat.completions.create(**params)

                latency_ms = int((time.time() - start_time) * 1000)

                choice = response.choices[0]
                content = choice.message.content or ""

                result = CompletionResult(
                    content=content,
                    model=model,
                    provider=self.name,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                    latency_ms=latency_ms,
                    finish_reason=choice.finish_reason,
                    metadata={
                        "seed": seed,
                        "temperature": temperature,
                        "response_id": response.id
                    }
                )

                self._record_request(result.total_tokens)

            else:
                # Simulated response for testing
                result = self._simulate_completion(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    seed=seed
                )
                result.latency_ms = int((time.time() - start_time) * 1000)

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._record_request(error=True)
            self._logger.error(f"OpenAI request failed: {e}")

            return CompletionResult(
                content="",
                model=model,
                provider=self.name,
                latency_ms=latency_ms,
                error=str(e)
            )

    def _simulate_completion(self, messages: List[Dict[str, str]],
                             model: str, temperature: float,
                             max_tokens: int, seed: Optional[int]) -> CompletionResult:
        """Simulate a completion response for testing."""
        # Get the last user message
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        # Generate simulated response
        prompt_tokens = self.count_tokens("\n".join(
            m.get("content", "") for m in messages
        ))

        # Simple simulation based on content
        response_content = f"[Simulated OpenAI response for {model}]\n"
        response_content += f"Processed {len(user_content)} characters.\n"
        response_content += f"Seed: {seed}, Temperature: {temperature}\n"
        response_content += "<confidence>HIGH</confidence>"

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
            metadata={"simulated": True}
        )

    def stream(self, messages: List[Dict[str, str]],
               **kwargs) -> Iterator[StreamChunk]:
        """
        Execute a streaming completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters

        Yields:
            StreamChunk objects
        """
        model = kwargs.get("model", self.config.default_model)
        temperature = kwargs.get("temperature", self.config.temperature)
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

        client = self._get_client()

        if client is not None:
            # Real streaming
            try:
                stream = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True
                )

                full_content = ""
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    full_content += delta

                    yield StreamChunk(
                        content=full_content,
                        delta=delta,
                        is_final=chunk.choices[0].finish_reason is not None,
                        finish_reason=chunk.choices[0].finish_reason
                    )

            except Exception as e:
                self._record_request(error=True)
                yield StreamChunk(
                    content="",
                    delta="",
                    is_final=True,
                    finish_reason="error"
                )
                raise AdapterRequestError(f"Streaming failed: {e}")
        else:
            # Simulated streaming
            content = f"[Simulated streaming for {model}]"
            yield StreamChunk(content=content, delta=content, is_final=True)

    def count_tokens(self, text: str) -> int:
        """
        Count tokens using tiktoken or estimation.

        Args:
            text: Text to count tokens for

        Returns:
            int: Token count
        """
        if self._tiktoken_available:
            try:
                import tiktoken
                if self._encoding is None:
                    self._encoding = tiktoken.encoding_for_model(
                        self.config.default_model
                    )
                return len(self._encoding.encode(text))
            except Exception:
                pass

        # Fallback: estimation (~4 chars per token)
        return len(text) // 4

    def validate_config(self, config: Dict) -> bool:
        """
        Validate OpenAI configuration.

        Args:
            config: Configuration dictionary

        Returns:
            bool: True if valid

        Raises:
            AdapterConfigError: If configuration is invalid
        """
        # Check API key
        api_key = config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise AdapterConfigError(
                "OpenAI API key required. Set api_key in config or "
                "OPENAI_API_KEY environment variable."
            )

        # Check model
        model = config.get("default_model", self.DEFAULT_MODEL)
        if model not in self.KNOWN_MODELS and not model.startswith("ft:"):
            self._logger.warning(
                f"Unknown model '{model}'. Known models: {self.KNOWN_MODELS}"
            )

        # Validate temperature
        temperature = config.get("temperature", 0.7)
        if not 0 <= temperature <= 2:
            raise AdapterConfigError(
                f"Temperature must be between 0 and 2, got {temperature}"
            )

        # Validate max_tokens
        max_tokens = config.get("max_tokens", 4096)
        if max_tokens < 1:
            raise AdapterConfigError(
                f"max_tokens must be positive, got {max_tokens}"
            )

        return True

    def get_capabilities(self) -> List[AdapterCapability]:
        """
        Get OpenAI adapter capabilities.

        Returns:
            List of supported capabilities
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

    def get_available_models(self) -> List[str]:
        """
        Get list of known available models.

        Returns:
            List of model names
        """
        return list(self.KNOWN_MODELS)
