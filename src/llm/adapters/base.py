"""
ITEM-INT-132: Provider Adapter Base Class for TITAN Protocol.

This module defines the abstract base class for all LLM provider adapters.
Each adapter must implement this interface to be registered with the
ProviderAdapterRegistry.

The adapter pattern allows TITAN Protocol to support multiple LLM providers
with a consistent interface, enabling:
- Easy provider switching
- Custom provider plugins
- Unified error handling
- Consistent telemetry across providers

Author: TITAN FUSE Team
Version: 4.1.0
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Iterator, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

from src.utils.timezone import now_utc, now_utc_iso


class AdapterCapability(Enum):
    """Capabilities that an adapter may support."""
    STREAMING = "streaming"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    SEED_PARAMETER = "seed_parameter"
    TEMPERATURE_CONTROL = "temperature_control"
    TOKEN_COUNTING = "token_counting"
    SYSTEM_PROMPT = "system_prompt"
    MULTI_MODAL = "multi_modal"


@dataclass
class CompletionResult:
    """
    Result from a completion request.

    Standardizes the response format across all providers.

    Attributes:
        content: The generated text content
        model: The model that generated the response
        provider: The provider name
        prompt_tokens: Number of tokens in the prompt
        completion_tokens: Number of tokens in the completion
        total_tokens: Total tokens used
        latency_ms: Request latency in milliseconds
        finish_reason: Why the completion stopped
        confidence: Optional confidence score (0.0-1.0)
        metadata: Additional provider-specific metadata
    """
    content: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "finish_reason": self.finish_reason,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "error": self.error
        }


@dataclass
class StreamChunk:
    """
    A chunk from a streaming response.

    Attributes:
        content: The text content in this chunk
        delta: Incremental content (for streaming)
        is_final: Whether this is the final chunk
        finish_reason: Why the stream stopped (if final)
    """
    content: str
    delta: str = ""
    is_final: bool = False
    finish_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "delta": self.delta,
            "is_final": self.is_final,
            "finish_reason": self.finish_reason
        }


@dataclass
class AdapterConfig:
    """
    Configuration for a provider adapter.

    Attributes:
        api_key: API key for authentication
        api_base: Base URL for API requests
        default_model: Default model to use
        max_tokens: Maximum tokens per request
        temperature: Default temperature
        timeout_seconds: Request timeout
        retry_count: Number of retries on failure
        retry_delay_ms: Delay between retries
        extra: Provider-specific configuration
    """
    api_key: Optional[str] = None
    api_base: Optional[str] = None
    default_model: str = "unknown"
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout_seconds: int = 30
    retry_count: int = 3
    retry_delay_ms: int = 1000
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "api_key": "***" if self.api_key else None,  # Redacted
            "api_base": self.api_base,
            "default_model": self.default_model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "retry_delay_ms": self.retry_delay_ms,
            "extra": self.extra
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'AdapterConfig':
        """Create from dictionary."""
        return cls(
            api_key=data.get("api_key"),
            api_base=data.get("api_base"),
            default_model=data.get("default_model", "unknown"),
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 0.7),
            timeout_seconds=data.get("timeout_seconds", 30),
            retry_count=data.get("retry_count", 3),
            retry_delay_ms=data.get("retry_delay_ms", 1000),
            extra=data.get("extra", {})
        )


class ProviderAdapter(ABC):
    """
    Abstract base class for LLM provider adapters.

    ITEM-INT-132: All provider adapters must implement this interface
    to be registered with the ProviderAdapterRegistry.

    The adapter provides a consistent interface for:
    - Completion requests (single and streaming)
    - Token counting
    - Configuration validation
    - Capability reporting

    Subclasses must implement:
    - complete(): Single completion request
    - stream(): Streaming completion request
    - count_tokens(): Token counting
    - validate_config(): Configuration validation
    - get_capabilities(): Supported capabilities

    Example:
        class MyProviderAdapter(ProviderAdapter):
            def __init__(self, config: AdapterConfig):
                super().__init__(config)
                self.name = "my_provider"

            def complete(self, messages: List[Dict], **kwargs) -> CompletionResult:
                # Implementation
                pass

            # ... other required methods
    """

    def __init__(self, config: AdapterConfig):
        """
        Initialize the adapter with configuration.

        Args:
            config: Adapter configuration
        """
        self.config = config
        self._logger = logging.getLogger(f"titan.adapters.{self.name}")
        self._request_count = 0
        self._total_tokens = 0
        self._error_count = 0

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Get the adapter name.

        Returns:
            str: Unique identifier for this adapter
        """
        pass

    @property
    def version(self) -> str:
        """
        Get the adapter version.

        Returns:
            str: Version string
        """
        return "1.0.0"

    @abstractmethod
    def complete(self, messages: List[Dict[str, str]],
                 **kwargs) -> CompletionResult:
        """
        Execute a completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            CompletionResult with the generated content

        Raises:
            AdapterError: If the request fails
        """
        pass

    @abstractmethod
    def stream(self, messages: List[Dict[str, str]],
               **kwargs) -> Iterator[StreamChunk]:
        """
        Execute a streaming completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional parameters

        Yields:
            StreamChunk objects

        Raises:
            AdapterError: If the request fails
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            int: Estimated token count
        """
        pass

    @abstractmethod
    def validate_config(self, config: Dict) -> bool:
        """
        Validate adapter configuration.

        Args:
            config: Configuration dictionary to validate

        Returns:
            bool: True if configuration is valid

        Raises:
            AdapterConfigError: If configuration is invalid
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> List[AdapterCapability]:
        """
        Get the capabilities supported by this adapter.

        Returns:
            List of supported capabilities
        """
        pass

    def has_capability(self, capability: AdapterCapability) -> bool:
        """
        Check if the adapter supports a specific capability.

        Args:
            capability: Capability to check

        Returns:
            bool: True if supported
        """
        return capability in self.get_capabilities()

    def get_default_model(self) -> str:
        """
        Get the default model for this adapter.

        Returns:
            str: Default model name
        """
        return self.config.default_model

    def get_stats(self) -> Dict:
        """
        Get adapter statistics.

        Returns:
            Dict with request counts, token usage, error counts
        """
        return {
            "name": self.name,
            "version": self.version,
            "request_count": self._request_count,
            "total_tokens": self._total_tokens,
            "error_count": self._error_count,
            "default_model": self.get_default_model()
        }

    def reset_stats(self) -> None:
        """Reset adapter statistics."""
        self._request_count = 0
        self._total_tokens = 0
        self._error_count = 0

    def _record_request(self, tokens: int = 0, error: bool = False) -> None:
        """
        Record request statistics.

        Args:
            tokens: Tokens used in this request
            error: Whether an error occurred
        """
        self._request_count += 1
        self._total_tokens += tokens
        if error:
            self._error_count += 1


class AdapterError(Exception):
    """Base exception for adapter errors."""
    pass


class AdapterConfigError(AdapterError):
    """Raised when adapter configuration is invalid."""
    pass


class AdapterRequestError(AdapterError):
    """Raised when a request to the provider fails."""
    pass


class AdapterNotAvailableError(AdapterError):
    """Raised when the adapter is not available or not registered."""
    pass
