"""
Tests for ITEM-OBS-07: Structured Logging Format

This module tests the structured logging implementation including
JSON formatting, component-level log levels, and context binding.

Author: TITAN FUSE Team
Version: 4.0.0
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock
from io import StringIO

from src.observability.structured_logging import (
    StructuredLogger,
    JSONLogFormatter,
    LoggingConfig,
    LogLevel,
    OutputDestination,
    OutputFormat,
    LEVEL_ORDER,
    DEFAULT_COMPONENT_LEVELS,
    init_logging,
    get_logger,
    configure_from_yaml,
    shutdown_logging,
    log_event,
    log_error,
    log_gate,
    log_performance,
)


class TestLogLevel:
    """Tests for LogLevel enum."""
    
    def test_log_level_values(self):
        """Test that log levels have correct string values."""
        assert LogLevel.DEBUG.value == "DEBUG"
        assert LogLevel.INFO.value == "INFO"
        assert LogLevel.WARN.value == "WARN"
        assert LogLevel.ERROR.value == "ERROR"
        assert LogLevel.CRITICAL.value == "CRITICAL"
    
    def test_level_order(self):
        """Test that level order is correct for filtering."""
        assert LEVEL_ORDER["CRITICAL"] < LEVEL_ORDER["ERROR"]
        assert LEVEL_ORDER["ERROR"] < LEVEL_ORDER["WARN"]
        assert LEVEL_ORDER["WARN"] < LEVEL_ORDER["INFO"]
        assert LEVEL_ORDER["INFO"] < LEVEL_ORDER["DEBUG"]


class TestDefaultComponentLevels:
    """Tests for default component log levels."""
    
    def test_eventbus_level(self):
        """Test that eventbus default level is INFO."""
        assert DEFAULT_COMPONENT_LEVELS["eventbus"] == "INFO"
    
    def test_gates_level(self):
        """Test that gates default level is DEBUG."""
        assert DEFAULT_COMPONENT_LEVELS["gates"] == "DEBUG"
    
    def test_llm_level(self):
        """Test that llm default level is WARN."""
        assert DEFAULT_COMPONENT_LEVELS["llm"] == "WARN"
    
    def test_storage_level(self):
        """Test that storage default level is INFO."""
        assert DEFAULT_COMPONENT_LEVELS["storage"] == "INFO"


class TestLoggingConfig:
    """Tests for LoggingConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = LoggingConfig()
        
        assert config.format == "json"
        assert config.output == "stdout"
        assert config.file_path == "logs/titan.log"
        assert config.default_level == "INFO"
        assert "eventbus" in config.component_levels
    
    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        config_dict = {
            "format": "text",
            "output": "file",
            "file_path": "/var/log/titan.log",
            "component_levels": {
                "custom_component": "DEBUG"
            },
            "default_level": "WARN"
        }
        
        config = LoggingConfig.from_dict(config_dict)
        
        assert config.format == "text"
        assert config.output == "file"
        assert config.file_path == "/var/log/titan.log"
        assert config.default_level == "WARN"
        assert config.component_levels["custom_component"] == "DEBUG"
        # Should still have defaults
        assert config.component_levels["eventbus"] == "INFO"
    
    def test_config_from_yaml(self):
        """Test creating config from YAML file."""
        yaml_content = """
logging:
  format: json
  output: both
  file_path: logs/test.log
  component_levels:
    eventbus: DEBUG
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            yaml_path = Path(f.name)
        
        try:
            config = LoggingConfig.from_yaml(yaml_path)
            assert config.format == "json"
            assert config.output == "both"
            assert config.file_path == "logs/test.log"
            assert config.component_levels["eventbus"] == "DEBUG"
        finally:
            os.unlink(yaml_path)


class TestJSONLogFormatter:
    """Tests for JSONLogFormatter."""
    
    def test_format_json_basic(self):
        """Test basic JSON formatting."""
        formatter = JSONLogFormatter(component="test")
        output = formatter.format("INFO", "Test message")
        
        parsed = json.loads(output)
        
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test message"
        assert parsed["component"] == "test"
        assert "timestamp" in parsed
        assert parsed["session_id"] == ""
        assert parsed["trace_id"] == ""
        assert parsed["extra"] == {}
    
    def test_format_json_with_all_fields(self):
        """Test JSON formatting with all fields."""
        formatter = JSONLogFormatter(
            component="test",
            session_id="session-123",
            trace_id="trace-456"
        )
        output = formatter.format(
            level="ERROR",
            message="Error occurred",
            component="custom",
            session_id="session-789",
            trace_id="trace-012",
            extra={"error_code": 500, "retry": True}
        )
        
        parsed = json.loads(output)
        
        assert parsed["level"] == "ERROR"
        assert parsed["message"] == "Error occurred"
        assert parsed["component"] == "custom"
        assert parsed["session_id"] == "session-789"
        assert parsed["trace_id"] == "trace-012"
        assert parsed["extra"]["error_code"] == 500
        assert parsed["extra"]["retry"] is True
    
    def test_format_json_timestamp_iso8601(self):
        """Test that timestamp is ISO8601 format."""
        formatter = JSONLogFormatter()
        output = formatter.format("INFO", "Test")
        
        parsed = json.loads(output)
        timestamp = parsed["timestamp"]
        
        # Should be parseable as ISO8601
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert dt is not None
    
    def test_format_text_basic(self):
        """Test basic text formatting."""
        formatter = JSONLogFormatter(component="test")
        output = formatter.format_text("INFO", "Test message")
        
        assert "[INFO" in output
        assert "Test message" in output
        assert "[test]" in output
    
    def test_format_text_with_context(self):
        """Test text formatting with session and trace IDs."""
        formatter = JSONLogFormatter(
            component="test",
            session_id="session-123",
            trace_id="trace-456"
        )
        output = formatter.format_text(
            level="ERROR",
            message="Error occurred",
            extra={"error_code": 500}
        )
        
        assert "[session:session-123]" in output
        assert "[trace:trace-456]" in output
        assert "error_code=500" in output
    
    def test_level_normalization(self):
        """Test that level is normalized to uppercase."""
        formatter = JSONLogFormatter()
        output = formatter.format("info", "Test")
        
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"


class TestStructuredLogger:
    """Tests for StructuredLogger class."""
    
    def test_log_info(self):
        """Test logging at INFO level."""
        logger = StructuredLogger(component="test")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.info("Test info message", extra_field="value")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "Test info message"
        assert parsed["extra"]["extra_field"] == "value"
    
    def test_log_debug(self):
        """Test logging at DEBUG level."""
        config = LoggingConfig(component_levels={"test": "DEBUG"})
        logger = StructuredLogger(component="test", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.debug("Debug message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "DEBUG"
    
    def test_log_warn(self):
        """Test logging at WARN level."""
        logger = StructuredLogger(component="test")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.warn("Warning message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "WARN"
    
    def test_log_error(self):
        """Test logging at ERROR level."""
        logger = StructuredLogger(component="test")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.error("Error message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "ERROR"
    
    def test_log_critical(self):
        """Test logging at CRITICAL level."""
        logger = StructuredLogger(component="test")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.critical("Critical message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "CRITICAL"
    
    def test_component_level_filtering(self):
        """Test that logs are filtered based on component level."""
        # LLM component has WARN level by default
        config = LoggingConfig(
            component_levels={"llm": "WARN"}
        )
        logger = StructuredLogger(component="llm", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            # INFO should be filtered
            logger.info("This should be filtered")
            info_output = mock_stdout.getvalue()
            
            # WARN should pass
            logger.warn("This should pass")
            warn_output = mock_stdout.getvalue()
        
        assert info_output == ""
        assert "This should pass" in warn_output
    
    def test_bind_context(self):
        """Test binding context to logger."""
        logger = StructuredLogger(component="test")
        bound_logger = logger.bind(request_id="req-123", user_id="user-456")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            bound_logger.info("Message with context")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["extra"]["request_id"] == "req-123"
        assert parsed["extra"]["user_id"] == "user-456"
        
        # Original logger should not have the context
        assert "request_id" not in logger._context
    
    def test_with_context(self):
        """Test creating logger with additional context."""
        logger = StructuredLogger(component="test", context={"initial": "value"})
        new_logger = logger.with_context({"additional": "context"})
        
        assert new_logger._context["initial"] == "value"
        assert new_logger._context["additional"] == "context"
        assert "additional" not in logger._context
    
    def test_with_session(self):
        """Test creating logger with session ID."""
        logger = StructuredLogger(component="test")
        session_logger = logger.with_session("session-abc")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            session_logger.info("Session message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["session_id"] == "session-abc"
    
    def test_with_trace(self):
        """Test creating logger with trace ID."""
        logger = StructuredLogger(component="test")
        trace_logger = logger.with_trace("trace-xyz")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            trace_logger.info("Trace message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["trace_id"] == "trace-xyz"
    
    def test_with_component(self):
        """Test creating logger with different component."""
        logger = StructuredLogger(component="original")
        new_logger = logger.with_component("new_component")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            new_logger.info("Component message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["component"] == "new_component"
    
    def test_text_format(self):
        """Test text output format."""
        config = LoggingConfig(format="text")
        logger = StructuredLogger(component="test", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.info("Text message")
            output = mock_stdout.getvalue()
        
        # Should not be JSON
        assert "{" not in output
        assert "[INFO" in output
        assert "Text message" in output
    
    def test_file_output(self):
        """Test file output destination."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.log")
            config = LoggingConfig(output="file", file_path=file_path)
            logger = StructuredLogger(component="test", config=config)
            
            logger.info("File message")
            logger.close()
            
            with open(file_path, 'r') as f:
                content = f.read()
            
            assert "File message" in content
            parsed = json.loads(content.strip())
            assert parsed["level"] == "INFO"
    
    def test_both_output(self):
        """Test both stdout and file output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.log")
            config = LoggingConfig(output="both", file_path=file_path)
            logger = StructuredLogger(component="test", config=config)
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                logger.info("Both message")
                stdout_output = mock_stdout.getvalue()
            
            logger.close()
            
            with open(file_path, 'r') as f:
                file_output = f.read()
            
            assert "Both message" in stdout_output
            assert "Both message" in file_output
    
    def test_context_manager(self):
        """Test logger as context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "test.log")
            config = LoggingConfig(output="file", file_path=file_path)
            
            with StructuredLogger(component="test", config=config) as logger:
                logger.info("Context message")
            
            # File should be closed now
            with open(file_path, 'r') as f:
                content = f.read()
            
            assert "Context message" in content


class TestComponentLevelFiltering:
    """Tests for component-level log level filtering."""
    
    def test_eventbus_filters_debug(self):
        """Test that eventbus component filters DEBUG messages."""
        config = LoggingConfig(component_levels={"eventbus": "INFO"})
        logger = StructuredLogger(component="eventbus", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.debug("Should be filtered")
            logger.info("Should pass")
            output = mock_stdout.getvalue()
        
        lines = [l for l in output.strip().split('\n') if l]
        assert len(lines) == 1
        assert "Should pass" in lines[0]
    
    def test_gates_allows_debug(self):
        """Test that gates component allows DEBUG messages."""
        config = LoggingConfig(component_levels={"gates": "DEBUG"})
        logger = StructuredLogger(component="gates", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.debug("Should pass")
            output = mock_stdout.getvalue()
        
        assert "Should pass" in output
    
    def test_llm_filters_info_and_debug(self):
        """Test that llm component filters INFO and DEBUG messages."""
        config = LoggingConfig(component_levels={"llm": "WARN"})
        logger = StructuredLogger(component="llm", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.debug("Should be filtered")
            logger.info("Should be filtered")
            logger.warn("Should pass")
            output = mock_stdout.getvalue()
        
        lines = [l for l in output.strip().split('\n') if l]
        assert len(lines) == 1
        assert "Should pass" in lines[0]
    
    def test_storage_filters_debug(self):
        """Test that storage component filters DEBUG messages."""
        config = LoggingConfig(component_levels={"storage": "INFO"})
        logger = StructuredLogger(component="storage", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.debug("Should be filtered")
            logger.info("Should pass")
            output = mock_stdout.getvalue()
        
        lines = [l for l in output.strip().split('\n') if l]
        assert len(lines) == 1
        assert "Should pass" in lines[0]
    
    def test_unknown_component_uses_default(self):
        """Test that unknown components use default level."""
        config = LoggingConfig(
            component_levels={"known": "DEBUG"},
            default_level="ERROR"
        )
        logger = StructuredLogger(component="unknown", config=config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.error("Should pass")
            logger.warn("Should be filtered")
            output = mock_stdout.getvalue()
        
        lines = [l for l in output.strip().split('\n') if l]
        assert len(lines) == 1
        assert "Should pass" in lines[0]


class TestGlobalLogger:
    """Tests for global logger functions."""
    
    def test_init_logging(self):
        """Test initializing global logging configuration."""
        config = LoggingConfig(format="text")
        init_logging(config)
        
        logger = get_logger("test")
        assert logger.config.format == "text"
        
        shutdown_logging()
    
    def test_init_logging_from_dict(self):
        """Test initializing logging from dictionary."""
        init_logging({"format": "json", "output": "stdout"})
        
        logger = get_logger("test")
        assert logger.config.format == "json"
        
        shutdown_logging()
    
    def test_get_logger_caching(self):
        """Test that get_logger caches loggers."""
        logger1 = get_logger("test", session_id="session1")
        logger2 = get_logger("test", session_id="session1")
        
        assert logger1 is logger2
        
        shutdown_logging()
    
    def test_get_logger_different_sessions(self):
        """Test that different sessions get different loggers."""
        logger1 = get_logger("test", session_id="session1")
        logger2 = get_logger("test", session_id="session2")
        
        assert logger1 is not logger2
        assert logger1._session_id != logger2._session_id
        
        shutdown_logging()


class TestConvenienceFunctions:
    """Tests for convenience logging functions."""
    
    def test_log_event(self):
        """Test log_event convenience function."""
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            log_event("test", "GATE_PASS", "Event occurred", extra="data")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "INFO"
        assert parsed["component"] == "test"
        assert parsed["extra"]["event_type"] == "GATE_PASS"
        
        shutdown_logging()
    
    def test_log_error(self):
        """Test log_error convenience function."""
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            log_error("test", "Something went wrong", code=500)
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "ERROR"
        assert parsed["component"] == "test"
        assert parsed["extra"]["code"] == 500
        
        shutdown_logging()
    
    def test_log_gate(self):
        """Test log_gate convenience function."""
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            log_gate("gates", "GATE-01", "PASSED", duration_ms=100)
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "INFO"
        assert parsed["component"] == "gates"
        assert parsed["extra"]["gate_id"] == "GATE-01"
        assert parsed["extra"]["status"] == "PASSED"
        
        shutdown_logging()
    
    def test_log_performance(self):
        """Test log_performance convenience function."""
        config = LoggingConfig(component_levels={"test": "DEBUG"})
        init_logging(config)
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            log_performance("test", "query", 150.5, rows=100)
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        assert parsed["level"] == "DEBUG"
        assert parsed["component"] == "test"
        assert parsed["extra"]["operation"] == "query"
        assert parsed["extra"]["duration_ms"] == 150.5
        
        shutdown_logging()


class TestThreadSafety:
    """Tests for thread safety of structured logging."""
    
    def test_concurrent_logging(self):
        """Test that concurrent logging is thread-safe."""
        import threading
        
        logger = StructuredLogger(component="test")
        messages = []
        errors = []
        
        def log_messages(thread_id):
            try:
                for i in range(10):
                    with patch('sys.stdout', new_callable=StringIO):
                        logger.info(f"Thread {thread_id} message {i}")
                    messages.append(f"Thread {thread_id} message {i}")
            except Exception as e:
                errors.append(e)
        
        threads = [
            threading.Thread(target=log_messages, args=(i,))
            for i in range(5)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(errors) == 0
        assert len(messages) == 50  # 5 threads * 10 messages


class TestIntegration:
    """Integration tests for structured logging."""
    
    def test_full_workflow(self):
        """Test complete logging workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "integration.log")
            config = LoggingConfig(
                format="json",
                output="both",
                file_path=file_path,
                component_levels={
                    "eventbus": "INFO",
                    "gates": "DEBUG",
                    "llm": "WARN",
                    "storage": "INFO"
                }
            )
            
            init_logging(config)
            
            # Get loggers for different components
            eventbus_logger = get_logger("eventbus").with_session("session-123")
            gates_logger = get_logger("gates").with_session("session-123")
            llm_logger = get_logger("llm").with_session("session-123")
            
            with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
                # EventBus - INFO level, should filter DEBUG
                eventbus_logger.debug("Should be filtered")
                eventbus_logger.info("Event processed")
                
                # Gates - DEBUG level, should pass everything
                gates_logger.debug("Gate evaluation started")
                gates_logger.info("Gate passed")
                
                # LLM - WARN level, should filter INFO and DEBUG
                llm_logger.info("Should be filtered")
                llm_logger.warn("Token limit approaching")
                
                output = mock_stdout.getvalue()
            
            lines = [l for l in output.strip().split('\n') if l]
            
            # Should have 3 log lines (eventbus INFO, gates DEBUG, gates INFO, llm WARN)
            assert len(lines) == 4
            
            # Verify content
            messages = [json.loads(l)["message"] for l in lines]
            assert "Event processed" in messages
            assert "Gate evaluation started" in messages
            assert "Gate passed" in messages
            assert "Token limit approaching" in messages
            assert "Should be filtered" not in messages
            
            shutdown_logging()
    
    def test_context_propagation(self):
        """Test that context propagates through logger hierarchy."""
        logger = StructuredLogger(component="test")
        
        # Bind initial context
        logger = logger.bind(request_id="req-123")
        
        # Add more context
        logger = logger.with_context({"user_id": "user-456"})
        
        # Add session
        logger = logger.with_session("session-789")
        
        with patch('sys.stdout', new_callable=StringIO) as mock_stdout:
            logger.info("Final message")
            output = mock_stdout.getvalue()
        
        parsed = json.loads(output.strip())
        
        assert parsed["extra"]["request_id"] == "req-123"
        assert parsed["extra"]["user_id"] == "user-456"
        assert parsed["session_id"] == "session-789"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
