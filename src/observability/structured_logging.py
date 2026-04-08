"""
TITAN FUSE Protocol - Structured Logging Format

JSON structured logging for standardized log output across the TITAN Protocol.
Provides component-level log level control and multiple output formats.

TASK-002: Advanced Observability & Transparency Layer
ITEM-OBS-07: Structured Logging Format

Features:
- JSON structured logging with ISO8601 timestamps
- Component-level log level configuration
- Context binding for request tracing
- Multiple output formats (JSON, text)
- Multiple output destinations (stdout, file, both)
"""

import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Union, List
from dataclasses import dataclass, field
from enum import Enum
import uuid
import copy


class LogLevel(Enum):
    """Log levels in order of severity (highest to lowest)."""
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"
    DEBUG = "DEBUG"


# Level mapping for comparison
LEVEL_ORDER = {
    "CRITICAL": 0,
    "ERROR": 1,
    "WARN": 2,
    "INFO": 3,
    "DEBUG": 4,
}


# Default component-level log levels as per requirements
DEFAULT_COMPONENT_LEVELS = {
    "eventbus": "INFO",
    "gates": "DEBUG",
    "llm": "WARN",
    "storage": "INFO",
}


class OutputDestination(Enum):
    """Log output destinations."""
    STDOUT = "stdout"
    FILE = "file"
    BOTH = "both"


class OutputFormat(Enum):
    """Log output formats."""
    JSON = "json"
    TEXT = "text"


@dataclass
class LoggingConfig:
    """
    Configuration for structured logging.
    
    Attributes:
        format: Output format (json or text)
        output: Output destination (stdout, file, or both)
        file_path: Path for log file when output is file or both
        component_levels: Dict mapping component names to log levels
        default_level: Default log level for unconfigured components
    """
    format: str = "json"
    output: str = "stdout"
    file_path: str = "logs/titan.log"
    component_levels: Dict[str, str] = field(default_factory=lambda: DEFAULT_COMPONENT_LEVELS.copy())
    default_level: str = "INFO"
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "LoggingConfig":
        """Create LoggingConfig from a dictionary."""
        component_levels = DEFAULT_COMPONENT_LEVELS.copy()
        if "component_levels" in config:
            component_levels.update(config["component_levels"])
        
        return cls(
            format=config.get("format", "json"),
            output=config.get("output", "stdout"),
            file_path=config.get("file_path", "logs/titan.log"),
            component_levels=component_levels,
            default_level=config.get("default_level", "INFO"),
        )
    
    @classmethod
    def from_yaml(cls, yaml_path: Path) -> "LoggingConfig":
        """Load configuration from YAML file."""
        import yaml
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract logging section if it exists
        logging_config = config.get("logging", {})
        structured_config = logging_config.get("structured", {})
        
        if not structured_config:
            # Fall back to top-level logging config
            structured_config = logging_config
        
        return cls.from_dict(structured_config)


class JSONLogFormatter:
    """
    JSON log formatter for structured logging.
    
    Formats log records as JSON with the following structure:
    {
        "timestamp": "ISO8601",
        "level": "DEBUG|INFO|WARN|ERROR|CRITICAL",
        "message": "string",
        "component": "string",
        "session_id": "string",
        "trace_id": "string",
        "extra": {...}
    }
    """
    
    def __init__(
        self,
        component: str = "titan",
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ):
        """
        Initialize the JSON log formatter.
        
        Args:
            component: Default component name for logs
            session_id: Session identifier for request tracing
            trace_id: Trace identifier for distributed tracing
        """
        self.component = component
        self.session_id = session_id
        self.trace_id = trace_id
    
    def format(
        self,
        level: str,
        message: str,
        component: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format a log entry as JSON.
        
        Args:
            level: Log level (DEBUG, INFO, WARN, ERROR, CRITICAL)
            message: Log message
            component: Component name (overrides default)
            session_id: Session ID (overrides default)
            trace_id: Trace ID (overrides default)
            extra: Additional fields to include
        
        Returns:
            JSON-formatted log string
        """
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": level.upper(),
            "message": message,
            "component": component or self.component,
            "session_id": session_id or self.session_id or "",
            "trace_id": trace_id or self.trace_id or "",
            "extra": extra or {}
        }
        
        return json.dumps(log_entry)
    
    def format_text(
        self,
        level: str,
        message: str,
        component: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format a log entry as human-readable text.
        
        Args:
            level: Log level
            message: Log message
            component: Component name
            session_id: Session ID
            trace_id: Trace ID
            extra: Additional fields
        
        Returns:
            Text-formatted log string
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        level_padded = level.upper().ljust(8)
        component_str = component or self.component
        
        # Use provided session_id/trace_id or fall back to instance values
        effective_session_id = session_id or self.session_id
        effective_trace_id = trace_id or self.trace_id
        
        parts = [f"[{timestamp}]", f"[{level_padded}]", f"[{component_str}]"]
        
        if effective_session_id:
            parts.append(f"[session:{effective_session_id}]")
        if effective_trace_id:
            parts.append(f"[trace:{effective_trace_id}]")
        
        parts.append(message)
        
        if extra:
            extra_str = " ".join(f"{k}={v}" for k, v in extra.items())
            parts.append(f"| {extra_str}")
        
        return " ".join(parts)


class StructuredLogger:
    """
    Structured logger with context binding and component-level log control.
    
    Features:
    - JSON or text output format
    - Component-level log level filtering
    - Context binding for request tracing
    - Child logger creation with inherited context
    
    Usage:
        logger = StructuredLogger(component="eventbus")
        logger.info("Event processed", event_type="GATE_PASS")
        
        # Bind context
        request_logger = logger.bind(request_id="req-123")
        request_logger.info("Processing request")
        
        # Create child with additional context
        child_logger = logger.with_context({"user_id": "user-456"})
    """
    
    def __init__(
        self,
        component: str = "titan",
        config: Optional[LoggingConfig] = None,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ):
        """
        Initialize the structured logger.
        
        Args:
            component: Component name for this logger
            config: Logging configuration
            context: Default context for all log messages
            session_id: Session identifier
            trace_id: Trace identifier
        """
        self.component = component
        self.config = config or LoggingConfig()
        self._context = context or {}
        self._session_id = session_id
        self._trace_id = trace_id
        self._formatter = JSONLogFormatter(
            component=component,
            session_id=session_id,
            trace_id=trace_id
        )
        self._lock = threading.Lock()
        self._file_handle: Optional[Any] = None
        
        # Initialize file output if needed
        if self.config.output in (OutputDestination.FILE.value, OutputDestination.BOTH.value):
            self._init_file_output()
    
    def _init_file_output(self) -> None:
        """Initialize file output for logging."""
        file_path = Path(self.config.file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_handle = open(file_path, 'a', encoding='utf-8')
    
    def _get_component_level(self, component: str) -> str:
        """Get the configured log level for a component."""
        return self.config.component_levels.get(component, self.config.default_level)
    
    def _should_log(self, level: str, component: str) -> bool:
        """Check if a log message should be logged based on component level."""
        component_level = self._get_component_level(component)
        message_level = level.upper()
        
        return LEVEL_ORDER.get(message_level, 3) <= LEVEL_ORDER.get(component_level, 3)
    
    def _write(self, formatted_message: str) -> None:
        """Write the formatted message to configured outputs."""
        with self._lock:
            if self.config.output in (OutputDestination.STDOUT.value, OutputDestination.BOTH.value):
                print(formatted_message, file=sys.stdout)
            
            if self.config.output in (OutputDestination.FILE.value, OutputDestination.BOTH.value):
                if self._file_handle:
                    self._file_handle.write(formatted_message + "\n")
                    self._file_handle.flush()
    
    def log(self, level: str, message: str, **kwargs) -> None:
        """
        Log a message at the specified level.
        
        Args:
            level: Log level (DEBUG, INFO, WARN, ERROR, CRITICAL)
            message: Log message
            **kwargs: Additional fields to include in the log entry
        """
        if not self._should_log(level, self.component):
            return
        
        # Merge context with kwargs
        extra = {**self._context, **kwargs}
        
        # Format based on config
        if self.config.format == OutputFormat.JSON.value:
            formatted = self._formatter.format(
                level=level,
                message=message,
                component=self.component,
                session_id=self._session_id,
                trace_id=self._trace_id,
                extra=extra
            )
        else:
            formatted = self._formatter.format_text(
                level=level,
                message=message,
                component=self.component,
                session_id=self._session_id,
                trace_id=self._trace_id,
                extra=extra
            )
        
        self._write(formatted)
    
    def debug(self, message: str, **kwargs) -> None:
        """Log a DEBUG level message."""
        self.log("DEBUG", message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """Log an INFO level message."""
        self.log("INFO", message, **kwargs)
    
    def warn(self, message: str, **kwargs) -> None:
        """Log a WARN level message."""
        self.log("WARN", message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """Log an ERROR level message."""
        self.log("ERROR", message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """Log a CRITICAL level message."""
        self.log("CRITICAL", message, **kwargs)
    
    def bind(self, **kwargs) -> "StructuredLogger":
        """
        Create a new logger with additional bound context.
        
        Args:
            **kwargs: Context fields to bind
        
        Returns:
            New StructuredLogger instance with bound context
        """
        new_context = {**self._context, **kwargs}
        return StructuredLogger(
            component=self.component,
            config=self.config,
            context=new_context,
            session_id=self._session_id,
            trace_id=self._trace_id
        )
    
    def with_context(self, context: Dict[str, Any]) -> "StructuredLogger":
        """
        Create a new logger with additional context.
        
        Args:
            context: Context dictionary to merge with existing context
        
        Returns:
            New StructuredLogger instance with merged context
        """
        new_context = {**self._context, **context}
        return StructuredLogger(
            component=self.component,
            config=self.config,
            context=new_context,
            session_id=self._session_id,
            trace_id=self._trace_id
        )
    
    def with_component(self, component: str) -> "StructuredLogger":
        """
        Create a new logger for a different component.
        
        Args:
            component: New component name
        
        Returns:
            New StructuredLogger instance for the specified component
        """
        return StructuredLogger(
            component=component,
            config=self.config,
            context=self._context.copy(),
            session_id=self._session_id,
            trace_id=self._trace_id
        )
    
    def with_session(self, session_id: str) -> "StructuredLogger":
        """
        Create a new logger with a session ID.
        
        Args:
            session_id: Session identifier
        
        Returns:
            New StructuredLogger instance with session ID
        """
        return StructuredLogger(
            component=self.component,
            config=self.config,
            context=self._context.copy(),
            session_id=session_id,
            trace_id=self._trace_id
        )
    
    def with_trace(self, trace_id: str) -> "StructuredLogger":
        """
        Create a new logger with a trace ID.
        
        Args:
            trace_id: Trace identifier
        
        Returns:
            New StructuredLogger instance with trace ID
        """
        return StructuredLogger(
            component=self.component,
            config=self.config,
            context=self._context.copy(),
            session_id=self._session_id,
            trace_id=trace_id
        )
    
    def close(self) -> None:
        """Close any open file handles."""
        with self._lock:
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
    
    def __enter__(self) -> "StructuredLogger":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


# Global logger configuration
_global_config: Optional[LoggingConfig] = None
_global_loggers: Dict[str, StructuredLogger] = {}
_loggers_lock = threading.Lock()


def init_logging(config: Optional[Union[LoggingConfig, Dict[str, Any]]] = None) -> None:
    """
    Initialize the global logging configuration.
    
    Args:
        config: LoggingConfig instance or dictionary
    """
    global _global_config
    
    if isinstance(config, dict):
        config = LoggingConfig.from_dict(config)
    
    _global_config = config or LoggingConfig()


def get_logger(
    component: str = "titan",
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None
) -> StructuredLogger:
    """
    Get or create a structured logger for a component.
    
    Args:
        component: Component name
        session_id: Optional session ID
        trace_id: Optional trace ID
    
    Returns:
        StructuredLogger instance
    """
    config = _global_config or LoggingConfig()
    
    with _loggers_lock:
        cache_key = f"{component}:{session_id}:{trace_id}"
        if cache_key not in _global_loggers:
            _global_loggers[cache_key] = StructuredLogger(
                component=component,
                config=config,
                session_id=session_id,
                trace_id=trace_id
            )
        return _global_loggers[cache_key]


def configure_from_yaml(yaml_path: Path) -> None:
    """
    Configure logging from a YAML file.
    
    Args:
        yaml_path: Path to YAML configuration file
    """
    config = LoggingConfig.from_yaml(yaml_path)
    init_logging(config)


def shutdown_logging() -> None:
    """Shutdown all loggers and close file handles."""
    global _global_loggers
    
    with _loggers_lock:
        for logger in _global_loggers.values():
            logger.close()
        _global_loggers.clear()


# Convenience functions for common logging operations
def log_event(component: str, event_type: str, message: str, **kwargs) -> None:
    """Log an event with standardized format."""
    logger = get_logger(component)
    logger.info(message, event_type=event_type, **kwargs)


def log_error(component: str, error: str, **kwargs) -> None:
    """Log an error with standardized format."""
    logger = get_logger(component)
    logger.error(error, **kwargs)


def log_gate(component: str, gate_id: str, status: str, **kwargs) -> None:
    """Log a gate evaluation."""
    logger = get_logger(component)
    logger.info(f"Gate {gate_id} {status}", gate_id=gate_id, status=status, **kwargs)


def log_performance(component: str, operation: str, duration_ms: float, **kwargs) -> None:
    """Log a performance metric."""
    logger = get_logger(component)
    logger.debug(
        f"Operation {operation} completed",
        operation=operation,
        duration_ms=duration_ms,
        **kwargs
    )
