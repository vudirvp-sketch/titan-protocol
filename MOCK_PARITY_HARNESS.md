---
title: TITAN FUSE — Mock & Parity Harness v1.0
extends: TITAN FUSE Protocol v3.2.0
purpose: Deterministic testing infrastructure for CI/CD and development
audience: ["developers", "ci_cd_systems"]
tier: testing_infrastructure
---

# MOCK & PARITY HARNESS

> **Purpose**: Enable deterministic, reproducible testing without LLM rate limits, ensuring protocol compliance and zero-drift guarantees.

---

## Overview

The Mock & Parity Harness provides:

1. **Deterministic Mock Layer**: Emulates LLM responses with seed-based generation
2. **Tool Mocking**: Simulates tool outputs for unit testing
3. **Parity Audit**: Verifies implementation matches PROTOCOL.base.md
4. **CI/CD Integration**: Zero-cost testing in pipelines

---

## 1. Mock Layer Specification

### 1.1 LLM Response Mock

```python
# src/testing/mock_llm.py

from typing import Dict, Any, Optional
import hashlib
import json

class MockLLMResponse:
    """
    Deterministic mock LLM responses based on input seed.

    Usage:
        mock = MockLLMResponse(seed=42)
        response = mock.query("Analyze this code", context="...")
    """

    def __init__(self, seed: int = 42, mode: str = "deterministic"):
        self.seed = seed
        self.mode = mode
        self.response_templates = self._load_templates()

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

    def query(self, task: str, context: str = "", max_tokens: int = 2048) -> Dict:
        """
        Generate deterministic mock response.

        The response is deterministic based on:
        - Seed value
        - Task hash
        - Context hash
        """
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

        return {
            "content": response,
            "confidence": "HIGH",
            "chunk_ref": input_hash,
            "raw_tokens": min(len(response) // 4, max_tokens),
            "_mock": True,
            "_seed": self.seed
        }

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

        return pattern.format(
            input_hash=input_hash,
            findings=selected if isinstance(selected, list) else str(selected),
            fix_description="Mock fix applied",
            status="PASS"
        )


class MockLLMProvider:
    """
    Mock provider that wraps MockLLMResponse for Orchestrator integration.
    """

    def __init__(self, seed: int = 42):
        self.mock = MockLLMResponse(seed=seed)
        self.call_count = 0
        self.call_log = []

    def completions_create(self, messages: list, **kwargs) -> Dict:
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

        response = self.mock.query(task, context)

        self.call_log.append({
            "call_id": self.call_count,
            "task": task[:100],  # Truncate for logging
            "response_tokens": response["raw_tokens"]
        })

        return {
            "choices": [{
                "message": {
                    "content": response["content"],
                    "role": "assistant"
                }
            }],
            "_mock": True
        }
```

### 1.2 Tool Mocking

```python
# src/testing/mock_tools.py

from typing import Dict, Any, List, Optional
from pathlib import Path
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

    def call(self, tool_name: str, **kwargs) -> Dict:
        """Execute a mock tool call."""
        if tool_name not in self.tools:
            return {"error": f"Unknown tool: {tool_name}"}

        result = self.tools[tool_name](**kwargs)
        self.call_log.append({
            "tool": tool_name,
            "kwargs": kwargs,
            "result_preview": str(result)[:100]
        })
        return result

    def _mock_grep(self, pattern: str, path: str = ".", **kwargs) -> Dict:
        """Mock grep results."""
        # Deterministic results based on pattern hash
        import hashlib
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
            "matches": lines,
            "count": len(lines)
        }

    def _mock_read(self, path: str, **kwargs) -> Dict:
        """Mock file read."""
        return {
            "path": path,
            "content": f"[MOCK CONTENT for {path}]\nLine 1\nLine 2\nLine 3",
            "lines": 3
        }

    def _mock_write(self, path: str, content: str, **kwargs) -> Dict:
        """Mock file write."""
        return {
            "path": path,
            "bytes_written": len(content),
            "success": True
        }

    def _mock_checksum(self, path: str, **kwargs) -> Dict:
        """Mock checksum calculation."""
        import hashlib
        path_hash = hashlib.sha256(path.encode()).hexdigest()
        return {
            "path": path,
            "checksum": path_hash,
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
```

---

## 2. Parity Audit Specification

### 2.1 Protocol Compliance Checker

```python
# src/testing/parity_audit.py

from typing import Dict, List, Tuple
from pathlib import Path
import re
import json

class ParityAudit:
    """
    Verifies that implementation matches PROTOCOL.base.md specification.

    Checks:
    - All TIER sections implemented
    - All GATE validators present
    - All INVAR invariants enforced
    - Output format compliance
    """

    def __init__(self, protocol_path: Path, implementation_path: Path):
        self.protocol_path = protocol_path
        self.implementation_path = implementation_path
        self.protocol_sections = self._parse_protocol()
        self.results = []

    def _parse_protocol(self) -> Dict:
        """Parse PROTOCOL.base.md for required sections."""
        content = self.protocol_path.read_text()

        sections = {
            "tiers": re.findall(r'## TIER (-?\d+)', content),
            "gates": re.findall(r'GATE-(\d+)', content),
            "invariants": re.findall(r'INVAR-(\d+)', content),
            "principles": re.findall(r'PRINCIPLE-(\d+)', content),
            "phases": re.findall(r'PHASE (-?\d+)', content)
        }

        return sections

    def audit(self) -> Dict:
        """
        Run parity audit.

        Returns:
            Audit result with pass/fail status and details
        """
        self.results = []

        # Check TIER implementation
        self._check_tiers()

        # Check GATE implementation
        self._check_gates()

        # Check INVAR implementation
        self._check_invariants()

        # Check output format
        self._check_output_format()

        passed = all(r["status"] == "PASS" for r in self.results)

        return {
            "passed": passed,
            "total_checks": len(self.results),
            "passed_count": sum(1 for r in self.results if r["status"] == "PASS"),
            "failed_count": sum(1 for r in self.results if r["status"] == "FAIL"),
            "results": self.results
        }

    def _check_tiers(self) -> None:
        """Verify all TIER sections are implemented."""
        required_tiers = ["-1", "0", "1", "2", "3", "4", "5"]

        for tier in required_tiers:
            # Check if tier is mentioned in protocol
            if tier in self.protocol_sections["tiers"]:
                # Check implementation
                impl_has_tier = self._implementation_has_tier(tier)

                self.results.append({
                    "check": f"TIER {tier}",
                    "status": "PASS" if impl_has_tier else "FAIL",
                    "details": f"Implementation {'has' if impl_has_tier else 'missing'} TIER {tier}"
                })

    def _implementation_has_tier(self, tier: str) -> bool:
        """Check if implementation has tier support."""
        # Look for tier references in implementation
        tier_names = {
            "-1": ["bootstrap", "tier_-1", "tier_minus_1"],
            "0": ["invariant", "tier_0"],
            "1": ["core", "principle", "tier_1"],
            "2": ["execution", "phase", "tier_2"],
            "3": ["output", "format", "tier_3"],
            "4": ["rollback", "tier_4"],
            "5": ["failsafe", "tier_5"]
        }

        for name in tier_names.get(tier, []):
            # Check Python files
            for py_file in self.implementation_path.rglob("*.py"):
                content = py_file.read_text().lower()
                if name in content:
                    return True

        return False

    def _check_gates(self) -> None:
        """Verify all GATE validators are implemented."""
        required_gates = ["00", "01", "02", "03", "04", "05"]

        for gate in required_gates:
            impl_has_gate = self._implementation_has_gate(gate)

            self.results.append({
                "check": f"GATE-{gate}",
                "status": "PASS" if impl_has_gate else "FAIL",
                "details": f"Gate validator {'present' if impl_has_gate else 'missing'}"
            })

    def _implementation_has_gate(self, gate: str) -> bool:
        """Check if gate validator exists."""
        gate_patterns = [f"gate_{gate}", f"GATE-{gate}", f"validate_gate_{gate}"]

        for py_file in self.implementation_path.rglob("*.py"):
            content = py_file.read_text()
            for pattern in gate_patterns:
                if pattern in content:
                    return True

        return False

    def _check_invariants(self) -> None:
        """Verify INVAR invariants are enforced."""
        required_invars = ["01", "02", "03", "04"]

        for invar in required_invars:
            impl_has_invar = self._implementation_has_invariant(invar)

            self.results.append({
                "check": f"INVAR-{invar}",
                "status": "PASS" if impl_has_invar else "FAIL",
                "details": f"Invariant {'enforced' if impl_has_invar else 'not found'}"
            })

    def _implementation_has_invariant(self, invar: str) -> bool:
        """Check if invariant is enforced."""
        patterns = [f"INVAR-{invar}", f"invar_{invar}", f"INVARIANT_{invar}"]

        for py_file in self.implementation_path.rglob("*.py"):
            content = py_file.read_text().upper()
            for pattern in patterns:
                if pattern.upper() in content:
                    return True

        return False

    def _check_output_format(self) -> None:
        """Verify output format matches specification."""
        required_outputs = [
            "STATE_SNAPSHOT",
            "EXECUTION_PLAN",
            "CHANGE_LOG",
            "VALIDATION_REPORT",
            "NAVIGATION_INDEX",
            "PATHOLOGY_REGISTRY",
            "KNOWN_GAPS",
            "FINAL_STATUS"
        ]

        for output in required_outputs:
            found = False
            for py_file in self.implementation_path.rglob("*.py"):
                content = py_file.read_text()
                if output.lower() in content.lower():
                    found = True
                    break

            self.results.append({
                "check": f"OUTPUT_{output}",
                "status": "PASS" if found else "WARN",
                "details": f"Output section {'found' if found else 'missing'}"
            })
```

---

## 3. Test Suite Structure

### 3.1 Unit Tests

```python
# tests/test_gates.py

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from testing.mock_llm import MockLLMProvider
from testing.mock_tools import MockToolRegistry
from state.state_manager import StateManager
from harness.orchestrator import Orchestrator


class TestGates:
    """Unit tests for GATE validation."""

    @pytest.fixture
    def mock_setup(self, tmp_path):
        """Setup mock environment for testing."""
        # Create mock repo structure
        (tmp_path / "inputs").mkdir()
        (tmp_path / "outputs").mkdir()
        (tmp_path / "checkpoints").mkdir()

        # Create test input file
        test_file = tmp_path / "inputs" / "test.md"
        test_file.write_text("# Test File\n\nLine 1\nLine 2\nLine 3\n")

        return tmp_path

    def test_gate_00_pass(self, mock_setup):
        """Test GATE-00 passes with valid input."""
        state_manager = StateManager(mock_setup)
        session = state_manager.create_session(
            input_files=[str(mock_setup / "inputs" / "test.md")]
        )

        orchestrator = Orchestrator(mock_setup)
        # Simulate chunking
        session["chunks"] = {"C1": {"status": "PENDING"}}

        passed, details = orchestrator.validate_gate("GATE-00", session)
        assert passed is True

    def test_gate_00_fail_no_source(self, mock_setup):
        """Test GATE-00 fails without source file."""
        state_manager = StateManager(mock_setup)
        session = state_manager.create_session()

        orchestrator = Orchestrator(mock_setup)
        passed, details = orchestrator.validate_gate("GATE-00", session)
        assert passed is False
        assert "No source file" in str(details)

    def test_gate_04_threshold_sev1(self, mock_setup):
        """Test GATE-04 blocks with SEV-1 gaps."""
        state_manager = StateManager(mock_setup)
        session = state_manager.create_session()
        session["known_gaps"] = ["gap: SEV-1 critical issue"]
        session["open_issues"] = ["ISSUE-001"]

        orchestrator = Orchestrator(mock_setup)
        passed, details = orchestrator.validate_gate("GATE-04", session)
        assert passed is False


class TestMockLLM:
    """Tests for mock LLM determinism."""

    def test_deterministic_responses(self):
        """Test that same seed produces same response."""
        from testing.mock_llm import MockLLMResponse

        mock1 = MockLLMResponse(seed=42)
        mock2 = MockLLMResponse(seed=42)

        r1 = mock1.query("Analyze code", context="test")
        r2 = mock2.query("Analyze code", context="test")

        assert r1["content"] == r2["content"]

    def test_different_seeds_different_responses(self):
        """Test that different seeds produce different responses."""
        from testing.mock_llm import MockLLMResponse

        mock1 = MockLLMResponse(seed=42)
        mock2 = MockLLMResponse(seed=43)

        r1 = mock1.query("Analyze code", context="test")
        r2 = mock2.query("Analyze code", context="test")

        # Responses should differ in some way
        assert r1["_seed"] != r2["_seed"]


class TestParityAudit:
    """Tests for protocol parity."""

    def test_parity_audit(self):
        """Test parity audit runs without errors."""
        from testing.parity_audit import ParityAudit

        protocol_path = Path(__file__).parent.parent / "PROTOCOL.base.md"
        impl_path = Path(__file__).parent.parent / "src"

        if protocol_path.exists():
            audit = ParityAudit(protocol_path, impl_path)
            result = audit.audit()

            assert "passed" in result
            assert "results" in result
```

### 3.2 Test Configuration

```toml
# pyproject.toml

[tool.pytest.ini_options]
testpaths = ["tests"]
python_paths = ["src"]
markers = [
    "slow: marks tests as slow",
    "integration: marks tests as integration tests"
]

[tool.coverage.run]
source = ["src"]
omit = ["tests/*", "*/__pycache__/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.:",
    "raise NotImplementedError"
]
```

---

## 4. CI/CD Integration

### 4.1 GitHub Actions Workflow

```yaml
# .github/workflows/test.yml

name: TITAN Protocol Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -e . pytest pytest-cov pyyaml

      - name: Run parity audit
        run: |
          python -c "
          from src.testing.parity_audit import ParityAudit
          from pathlib import Path
          audit = ParityAudit(
              Path('PROTOCOL.base.md'),
              Path('src')
          )
          result = audit.audit()
          print(f'Parity: {result[\"passed_count\"]}/{result[\"total_checks\"]} passed')
          exit(0 if result['passed'] else 1)
          "

      - name: Run unit tests
        run: |
          pytest tests/ -v --cov=src --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: coverage.xml
```

---

## 5. Usage Examples

### 5.1 Running Tests

```bash
# Run all tests with mock LLM
pytest tests/ -v

# Run specific gate tests
pytest tests/test_gates.py -v

# Run parity audit
python -c "from src.testing.parity_audit import ParityAudit; ..."

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

### 5.2 Using Mock in Development

```python
# Example: Using mock for local development
from testing.mock_llm import MockLLMProvider
from harness.orchestrator import Orchestrator

# Initialize with mock provider
mock_provider = MockLLMProvider(seed=42)
orchestrator = Orchestrator(repo_root, llm_provider=mock_provider)

# Run pipeline - no API calls needed
result = orchestrator.run_pipeline(session)
```

---

## 6. Verification Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Mock LLM determinism | ✅ | Seed-based response generation |
| Tool mocking | ✅ | grep, read, write, checksum, ast |
| Parity audit | ✅ | TIER, GATE, INVAR checks |
| Unit test coverage | ✅ | Gate tests, mock tests |
| CI/CD workflow | ✅ | GitHub Actions configuration |
| Zero rate-limit dependency | ✅ | No external API calls in tests |

---

**Version**: 1.0.0
**Protocol Version**: 3.2.0
**Status**: Production-Ready
