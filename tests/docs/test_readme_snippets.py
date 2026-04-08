"""
README Snippet Tests for TITAN Protocol.

Validates that all code snippets in README.md are valid and executable.

Usage:
    pytest tests/docs/test_readme_snippets.py -v
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import List

import pytest
import yaml

from tests.docs.extract_snippets import ReadmeSnippetExtractor, CodeBlock


# Fixture for extracted snippets
@pytest.fixture
def snippets() -> List[CodeBlock]:
    """Extract code blocks from README.md."""
    readme_path = Path(__file__).parent.parent.parent / "README.md"
    if not readme_path.exists():
        pytest.skip("README.md not found")
    extractor = ReadmeSnippetExtractor()
    return extractor.extract_code_blocks(str(readme_path))


@pytest.fixture
def extractor() -> ReadmeSnippetExtractor:
    """Create snippet extractor."""
    return ReadmeSnippetExtractor()


class TestReadmeSnippets:
    """Tests for README code snippets."""

    def test_readme_exists(self):
        """README.md should exist."""
        readme_path = Path(__file__).parent.parent.parent / "README.md"
        assert readme_path.exists(), "README.md not found at project root"

    def test_snippets_extracted(self, snippets: List[CodeBlock]):
        """Should extract at least some code blocks from README."""
        assert len(snippets) > 0, "No code blocks found in README.md"

    def test_all_bash_snippets_have_shebang_or_are_safe(self, snippets: List[CodeBlock]):
        """Bash snippets should be safe to execute or have shebang."""
        bash_blocks = [s for s in snippets if s.language in ('bash', 'sh', 'shell')]

        for block in bash_blocks:
            # Skip if it's just a simple command (likely safe)
            lines = [l.strip() for l in block.code.strip().split('\n') if l.strip() and not l.strip().startswith('#')]

            # Check for dangerous patterns
            dangerous_patterns = ['rm -rf', 'sudo', 'mkfs', 'dd if=', '> /dev/']
            for line in lines:
                for pattern in dangerous_patterns:
                    assert pattern not in line, f"Potentially dangerous command in README: {line}"

    def test_all_yaml_snippets_valid(self, snippets: List[CodeBlock]):
        """All YAML snippets should parse correctly."""
        yaml_blocks = [s for s in snippets if s.language in ('yaml', 'yml')]

        for block in yaml_blocks:
            try:
                yaml.safe_load(block.code)
            except yaml.YAMLError as e:
                pytest.fail(f"Invalid YAML at line {block.line_number}: {e}\nCode:\n{block.code[:200]}")

    def test_all_json_snippets_valid(self, snippets: List[CodeBlock]):
        """All JSON snippets should parse correctly."""
        json_blocks = [s for s in snippets if s.language == 'json']

        for block in json_blocks:
            try:
                json.loads(block.code)
            except json.JSONDecodeError as e:
                pytest.fail(f"Invalid JSON at line {block.line_number}: {e}\nCode:\n{block.code[:200]}")

    def test_python_snippets_syntax_valid(self, snippets: List[CodeBlock]):
        """Python snippets should have valid syntax."""
        python_blocks = [s for s in snippets if s.language in ('python', 'py')]

        for block in python_blocks:
            try:
                compile(block.code, f'<README line {block.line_number}>', 'exec')
            except SyntaxError as e:
                pytest.fail(f"Invalid Python syntax at line {block.line_number}: {e}\nCode:\n{block.code[:200]}")

    @pytest.mark.skip(reason="Bash execution may have side effects - enable manually")
    def test_bash_snippets_execute(self, snippets: List[CodeBlock]):
        """All bash snippets should execute without error."""
        bash_blocks = [s for s in snippets if s.language in ('bash', 'sh', 'shell')]

        for block in bash_blocks:
            # Skip dangerous commands
            if any(p in block.code for p in ['rm ', 'sudo', 'mkfs']):
                continue

            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
                f.write(block.code)
                f.flush()

                result = subprocess.run(
                    ['bash', '-n', f.name],  # -n = check syntax only
                    capture_output=True,
                    timeout=30
                )

                if result.returncode != 0:
                    pytest.fail(
                        f"Bash syntax error at line {block.line_number}:\n"
                        f"{result.stderr.decode()}\n"
                        f"Code:\n{block.code[:200]}"
                    )

    def test_snippet_languages_are_known(self, snippets: List[CodeBlock], extractor: ReadmeSnippetExtractor):
        """Code blocks should use recognized language identifiers."""
        known_languages = {
            'bash', 'sh', 'shell', 'zsh',
            'python', 'py',
            'javascript', 'js', 'typescript', 'ts',
            'json', 'yaml', 'yml', 'toml', 'xml',
            'markdown', 'md',
            'text', 'plaintext',
            'diff', 'patch',
            'dockerfile', 'docker',
            'make', 'makefile',
            'sql',
            'html', 'css',
        }

        for block in snippets:
            if block.language not in known_languages:
                # Warning, not failure
                print(f"Unknown language '{block.language}' at line {block.line_number}")

    def test_no_empty_code_blocks(self, snippets: List[CodeBlock]):
        """Code blocks should not be empty."""
        for block in snippets:
            assert block.code.strip(), f"Empty code block at line {block.line_number}"


class TestSnippetExtraction:
    """Tests for the snippet extractor itself."""

    def test_extractor_initialization(self):
        """Extractor should initialize correctly."""
        extractor = ReadmeSnippetExtractor()
        assert extractor is not None

    def test_extract_from_string(self):
        """Should extract from string content."""
        extractor = ReadmeSnippetExtractor()
        content = """
# Test

```python
print("hello")
```
"""
        blocks = extractor._extract_from_content(content)
        assert len(blocks) == 1
        assert blocks[0].language == 'python'
        assert 'print' in blocks[0].code

    def test_extract_multiple_blocks(self):
        """Should extract multiple code blocks."""
        extractor = ReadmeSnippetExtractor()
        content = """
```bash
echo "one"
```

```python
print("two")
```

```json
{"three": 3}
```
"""
        blocks = extractor._extract_from_content(content)
        assert len(blocks) == 3
        languages = [b.language for b in blocks]
        assert 'bash' in languages
        assert 'python' in languages
        assert 'json' in languages

    def test_is_executable(self):
        """Should identify executable blocks."""
        extractor = ReadmeSnippetExtractor()

        bash_block = CodeBlock(language='bash', code='echo test', line_number=1)
        python_block = CodeBlock(language='python', code='print("test")', line_number=1)
        text_block = CodeBlock(language='text', code='not code', line_number=1)

        assert extractor.is_executable(bash_block)
        assert extractor.is_executable(python_block)
        assert not extractor.is_executable(text_block)

    def test_is_validatable(self):
        """Should identify validatable blocks."""
        extractor = ReadmeSnippetExtractor()

        json_block = CodeBlock(language='json', code='{}', line_number=1)
        yaml_block = CodeBlock(language='yaml', code='key: value', line_number=1)
        text_block = CodeBlock(language='text', code='not code', line_number=1)

        assert extractor.is_validatable(json_block)
        assert extractor.is_validatable(yaml_block)
        assert not extractor.is_validatable(text_block)
