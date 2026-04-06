"""
TITAN FUSE Protocol - Mock Tools for Testing

Deterministic mock tool outputs for CI/CD and development.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import hashlib
import json


class MockToolRegistry:
    """
    Mock registry for tool calls during testing.

    Provides deterministic outputs for:
    - grep/search operations
    - File operations
    - AST parsing
    - Checksum operations
    """

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.tools = {
            "grep": self._mock_grep,
            "read": self._mock_read,
            "write": self._mock_write,
            "checksum": self._mock_checksum,
            "ast_parse": self._mock_ast_parse
        }
        self.call_log = []
        self.file_system = {}  # In-memory file system

    def call(self, tool_name: str, **kwargs) -> Dict:
        """Execute a mock tool call."""
        if tool_name not in self.tools:
            return {"error": f"Unknown tool: {tool_name}"}

        result = self.tools[tool_name](**kwargs)
        self.call_log.append({
            "tool": tool_name,
            "kwargs": {k: str(v)[:50] for k, v in kwargs.items()},
            "result_status": "success" if "error" not in result else "error"
        })
        return result

    def set_file(self, path: str, content: str) -> None:
        """Set file content in mock file system."""
        self.file_system[path] = content

    def _mock_grep(self, pattern: str, path: str = ".", **kwargs) -> Dict:
        """Mock grep results."""
        # Deterministic results based on pattern hash
        pattern_hash = int(hashlib.md5(pattern.encode()).hexdigest()[:8], 16)

        # Generate deterministic line numbers
        lines = []
        base_line = (pattern_hash % 100) + 1
        for i in range(min(pattern_hash % 5 + 1, 3)):
            lines.append({
                "line": base_line + i * 50,
                "content": f"[MOCK] Match for pattern: {pattern[:30]}"
            })

        return {
            "pattern": pattern,
            "path": path,
            "matches": lines,
            "count": len(lines)
        }

    def _mock_read(self, path: str, **kwargs) -> Dict:
        """Mock file read."""
        if path in self.file_system:
            content = self.file_system[path]
        else:
            content = f"[MOCK CONTENT for {path}]\nLine 1\nLine 2\nLine 3"

        return {
            "path": path,
            "content": content,
            "lines": content.count("\n") + 1
        }

    def _mock_write(self, path: str, content: str, **kwargs) -> Dict:
        """Mock file write."""
        self.file_system[path] = content

        return {
            "path": path,
            "bytes_written": len(content),
            "success": True
        }

    def _mock_checksum(self, path: str, **kwargs) -> Dict:
        """Mock checksum calculation."""
        if path in self.file_system:
            content_hash = hashlib.sha256(self.file_system[path].encode()).hexdigest()
        else:
            path_hash = hashlib.sha256(path.encode()).hexdigest()
            content_hash = path_hash

        return {
            "path": path,
            "checksum": content_hash,
            "algorithm": "sha256"
        }

    def _mock_ast_parse(self, source: str, language: str = "python", **kwargs) -> Dict:
        """Mock AST parsing."""
        return {
            "language": language,
            "nodes": [
                {"type": "Module", "start": 0, "end": len(source)},
                {"type": "FunctionDef", "name": "mock_function", "start": 0, "end": 10}
            ],
            "success": True
        }

    def reset(self) -> None:
        """Reset mock state."""
        self.call_log.clear()
        self.file_system.clear()


class MockGrep:
    """Mock grep tool for testing."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def search(self, pattern: str, path: str = ".", **kwargs) -> List[Dict]:
        """Search for pattern in files."""
        pattern_hash = int(hashlib.md5(pattern.encode()).hexdigest()[:8], 16)
        base_line = (pattern_hash % 100) + 1

        return [{
            "file": f"{path}/mock_file.py",
            "line": base_line + i * 50,
            "content": f"[MOCK] {pattern[:30]}"
        } for i in range(min(pattern_hash % 3 + 1, 3))]


class MockFileOps:
    """Mock file operations for testing."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.files = {}

    def read(self, path: str) -> str:
        """Read file content."""
        if path in self.files:
            return self.files[path]
        return f"# Mock content for {path}\n\nline1\nline2\nline3\n"

    def write(self, path: str, content: str) -> bool:
        """Write file content."""
        self.files[path] = content
        return True

    def exists(self, path: str) -> bool:
        """Check if file exists."""
        return path in self.files or path.endswith((".md", ".py", ".json", ".yaml"))


class MockValidator:
    """Mock validator for testing GATE checks."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.validation_results = {}

    def set_result(self, gate: str, passed: bool, details: Dict = None) -> None:
        """Set predetermined validation result."""
        self.validation_results[gate] = {
            "passed": passed,
            "details": details or {}
        }

    def validate(self, gate: str, session: Dict) -> tuple:
        """Validate gate with predetermined result."""
        if gate in self.validation_results:
            result = self.validation_results[gate]
            return result["passed"], result["details"]

        # Default: pass all gates
        return True, {"gate": gate, "status": "PASS (mock)"}
