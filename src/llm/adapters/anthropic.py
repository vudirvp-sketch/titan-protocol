"""
ITEM-INT-132: Anthropic Provider Adapter for TITAN Protocol.

This module provides an adapter for Anthropic's Claude models, implementing
the ProviderAdapter interface for seamless integration with the
ProviderAdapterRegistry.

Supported Models:
- claude-3-opus, claude-3-opus-20240229
- claude-3-sonnet, claude-3-sonnet-20240229
- claude-3-haiku, claude-3-haiku-20240307
- claude-3-5-sonnet, claude-3-5-sonnet-20241022
- claude-3-5-haiku

Capabilities:
- Streaming responses
- Vision (all claude-3 models)
- Tool use
- System prompts
- Large context windows (200K tokens)

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


class AnthropicAdapter(ProviderAdapter):
    """
    Adapter for Anthropic Claude models.

    Implements the ProviderAdapter interface for Anthropic's API.

    Configuration:
        api_key: Anthropic API key (or ANTHROPIC_API_KEY env var)
        api_base: Custom API base URL (optional)
        default_model: Default model (e.g., "claude-3-opus")
        max_tokens: Maximum tokens per request (required by Anthropic)
        temperature: Sampling temperature (0.0-1.0)

    Note:
        Anthropic requires max_tokens to be specified for each request.
        The default is 4096, but can be up to the model's output limit.

    Example:
        config = AdapterConfig(
            api_key="sk-ant-...",
            default_model="claude-3-opus",
            max_tokens=4096,
            temperature=0.7
        )
        adapter = AnthropicAdapter(config)
        result = adapter.complete([
            {"role": "user", "content": "Hello!"}
        ], system="You are helpful.")
    """

    # Known Anthropic model names
    KNOWN_MODELS = {
        "claude-3-opus", "claude-3-opus-20240229",
        "claude-3-sonnet", "claude-3-sonnet-20240229",
        "claude-3-haiku", "claude-3-haiku-20240307",
        "claude-3-5-sonnet", "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-3-5-haiku", "claude-3-5-haiku-20241022"
    }

    # Default models for different use cases
    DEFAULT_MODEL = "claude-3-sonnet"
    POWERFUL_MODEL = "claude-3-opus"
    FAST_MODEL = "claude-3-haiku"

    def __init__(self, config: AdapterConfig):
        """
        Initialize Anthropic adapter.

        Args:
            config: Adapter configuration
        """
        super().__init__(config)

        # Use environment variable if API key not in config
        self._api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._api_base = config.api_base or os.environ.get("ANTHROPIC_API_BASE")

        # Set default model if not specified
        if config.default_model == "unknown":
            config.default_model = self.DEFAULT_MODEL

        self._client = None
        self._anthropic_available = False

        # Check for optional dependencies
        self._check_dependencies()

        self._logger.info(
            f"AnthropicAdapter initialized: model={config.default_model}, "
            f"api_key_set={self._api_key is not None}"
        )

    def _check_dependencies(self) -> None:
        """Check for optional dependencies."""
        try:
            import anthropic
            self._anthropic_available = True
        except ImportError:
            self._anthropic_available = False
            self._logger.warning(
                "anthropic package not installed. Using simulated responses."
            )

    @property
    def name(self) -> str:
        """Get adapter name."""
        return "anthropic"

    @property
    def version(self) -> str:
        """Get adapter version."""
        return "1.0.0"

    def _get_client(self):
        """Get or create Anthropic client."""
        if self._client is None and self._anthropic_available:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                base_url=self._api_base
            )
        return self._client

    def _convert_messages(self, messages: List[Dict[str, str]]) -> List[Dict]:
        """
        Convert OpenAI-style messages to Anthropic format.

        Anthropic uses a different message format:
        - System prompt is separate
        - Only 'user' and 'assistant' roles

        Args:
            messages: OpenAI-style messages

        Returns:
            Tuple of (anthropic_messages, system_prompt)
        """
        system_prompt = None
        anthropic_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role in ("user", "assistant"):
                anthropic_messages.append({
                    "role": role,
                    "content": content
                })

        return anthropic_messages, system_prompt

    def complete(self, messages: List[Dict[str, str]],
                 **kwargs) -> CompletionResult:
        """
        Execute a completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters:
                - model: Model override
                - temperature: Temperature override
                - max_tokens: Max tokens override (required by Anthropic)
                - system: System prompt (optional, extracted from messages)

        Returns:
            CompletionResult with the generated content
        """
        start_time = time.time()

        model = kwargs.get("model", self.config.default_model)
        temperature = kwargs.get("temperature", self.config.temperature)
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)
        system_override = kwargs.get("system")

        # Convert messages to Anthropic format
        anthropic_messages, system_from_messages = self._convert_messages(messages)
        system_prompt = system_override or system_from_messages

        try:
            client = self._get_client()

            if client is not None:
                # Real API call
                params = {
                    "model": model,
                    "messages": anthropic_messages,
                    "max_tokens": max_tokens
                }

                if temperature is not None:
                    params["temperature"] = temperature

                if system_prompt:
                    params["system"] = system_prompt

                response = client.messages.create(**params)

                latency_ms = int((time.time() - start_time) * 1000)

                # Extract content from response
                content = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        content += block.text

                result = CompletionResult(
                    content=content,
                    model=model,
                    provider=self.name,
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                    latency_ms=latency_ms,
                    finish_reason=response.stop_reason,
                    metadata={
                        "temperature": temperature,
                        "response_id": response.id,
                        "model_version": getattr(response, "model", model)
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
                    system_prompt=system_prompt
                )
                result.latency_ms = int((time.time() - start_time) * 1000)

            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            self._record_request(error=True)
            self._logger.error(f"Anthropic request failed: {e}")

            return CompletionResult(
                content="",
                model=model,
                provider=self.name,
                latency_ms=latency_ms,
                error=str(e)
            )

    def _simulate_completion(self, messages: List[Dict[str, str]],
                             model: str, temperature: float,
                             max_tokens: int,
                             system_prompt: Optional[str]) -> CompletionResult:
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
        response_content = f"[Simulated Anthropic response for {model}]\n"
        response_content += f"Processed {len(user_content)} characters.\n"
        if system_prompt:
            response_content += f"System: {system_prompt[:50]}...\n"
        response_content += f"Temperature: {temperature}\n"
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
            finish_reason="end_turn",
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

        anthropic_messages, system_prompt = self._convert_messages(messages)

        client = self._get_client()

        if client is not None:
            # Real streaming
            try:
                params = {
                    "model": model,
                    "messages": anthropic_messages,
                    "max_tokens": max_tokens
                }

                if temperature is not None:
                    params["temperature"] = temperature

                if system_prompt:
                    params["system"] = system_prompt

                with client.messages.stream(**params) as stream:
                    full_content = ""
                    for text in stream.text_stream:
                        full_content += text
                        yield StreamChunk(
                            content=full_content,
                            delta=text,
                            is_final=False
                        )

                    # Final chunk
                    yield StreamChunk(
                        content=full_content,
                        delta="",
                        is_final=True,
                        finish_reason="end_turn"
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
        Estimate token count for Anthropic models.

        Note: Anthropic uses a different tokenizer than OpenAI.
        This is a rough estimate.

        Args:
            text: Text to count tokens for

        Returns:
            int: Estimated token count
        """
        # Anthropic's tokenizer is roughly similar to GPT-4
        # Estimate: ~3.5 chars per token for Claude
        return len(text) // 3.5

    def validate_config(self, config: Dict) -> bool:
        """
        Validate Anthropic configuration.

        Args:
            config: Configuration dictionary

        Returns:
            bool: True if valid

        Raises:
            AdapterConfigError: If configuration is invalid
        """
        # Check API key
        api_key = config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise AdapterConfigError(
                "Anthropic API key required. Set api_key in config or "
                "ANTHROPIC_API_KEY environment variable."
            )

        # Check model
        model = config.get("default_model", self.DEFAULT_MODEL)
        if model not in self.KNOWN_MODELS:
            self._logger.warning(
                f"Unknown model '{model}'. Known models: {self.KNOWN_MODELS}"
            )

        # Validate temperature (Anthropic uses 0-1)
        temperature = config.get("temperature", 0.7)
        if not 0 <= temperature <= 1:
            raise AdapterConfigError(
                f"Temperature must be between 0 and 1 for Anthropic, got {temperature}"
            )

        # Validate max_tokens
        max_tokens = config.get("max_tokens", 4096)
        if max_tokens < 1:
            raise AdapterConfigError(
                f"max_tokens must be positive, got {max_tokens}"
            )

        # Anthropic has a maximum output of 4096 for most models
        if max_tokens > 4096:
            self._logger.warning(
                f"max_tokens={max_tokens} may exceed model output limit. "
                "Most Claude models have a 4096 token output limit."
            )

        return True

    def get_capabilities(self) -> List[AdapterCapability]:
        """
        Get Anthropic adapter capabilities.

        Returns:
            List of supported capabilities
        """
        return [
            AdapterCapability.STREAMING,
            AdapterCapability.VISION,
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
