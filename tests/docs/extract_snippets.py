"""
README Snippet Extractor for TITAN Protocol.

Extracts and validates code blocks from README.md for testing.

Usage:
    from tests.docs.extract_snippets import ReadmeSnippetExtractor

    extractor = ReadmeSnippetExtractor()
    blocks = extractor.extract_code_blocks("README.md")
    for block in blocks:
        print(f"{block.language}: {block.code[:50]}...")
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class CodeBlock:
    """Represents a code block extracted from markdown."""
    language: str
    code: str
    line_number: int
    file_path: Optional[str] = None

    def __repr__(self) -> str:
        return f"CodeBlock(language='{self.language}', lines={len(self.code.splitlines())}, line={self.line_number})"


class ReadmeSnippetExtractor:
    """
    Extracts code blocks from markdown files.

    Supports:
    - Standard fenced code blocks (```)
    - Language identification
    - Line number tracking
    - Executable block detection
    """

    # Languages that can be executed
    EXECUTABLE_LANGUAGES = {
        'bash', 'sh', 'shell', 'zsh',
        'python', 'py',
        'javascript', 'js', 'node',
        'ruby', 'rb',
        'perl', 'pl',
        'php',
    }

    # Languages that can be validated programmatically
    VALIDATABLE_LANGUAGES = {
        'json',
        'yaml', 'yml',
        'xml',
        'toml',
        'python', 'py',
        'javascript', 'js', 'typescript', 'ts',
    }

    def __init__(self, include_text_blocks: bool = False):
        """
        Initialize the extractor.

        Args:
            include_text_blocks: Whether to include blocks with 'text' or no language
        """
        self.include_text_blocks = include_text_blocks

    def extract_code_blocks(self, file_path: str) -> List[CodeBlock]:
        """
        Extract all code blocks from a markdown file.

        Args:
            file_path: Path to the markdown file

        Returns:
            List of CodeBlock objects
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = path.read_text(encoding='utf-8')
        return self._extract_from_content(content, str(path))

    def _extract_from_content(self, content: str, file_path: Optional[str] = None) -> List[CodeBlock]:
        """
        Extract code blocks from markdown content.

        Args:
            content: Markdown content
            file_path: Optional file path for reference

        Returns:
            List of CodeBlock objects
        """
        blocks = []

        # Pattern for fenced code blocks
        # Matches ```language\ncode\n```
        pattern = re.compile(
            r'^```(\w*)\n(.*?)^```',
            re.MULTILINE | re.DOTALL
        )

        for match in pattern.finditer(content):
            language = match.group(1) or 'text'
            code = match.group(2)

            # Calculate line number from match start
            line_number = content[:match.start()].count('\n') + 1

            # Skip text blocks unless explicitly included
            if language == 'text' and not self.include_text_blocks:
                continue

            block = CodeBlock(
                language=language.lower(),
                code=code,
                line_number=line_number,
                file_path=file_path
            )
            blocks.append(block)

        return blocks

    def get_block_language(self, block: CodeBlock) -> str:
        """
        Get the normalized language of a code block.

        Args:
            block: CodeBlock to check

        Returns:
            Normalized language name
        """
        # Normalize common aliases
        aliases = {
            'sh': 'bash',
            'shell': 'bash',
            'zsh': 'bash',
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'yml': 'yaml',
        }
        return aliases.get(block.language, block.language)

    def is_executable(self, block: CodeBlock) -> bool:
        """
        Check if a code block can be executed.

        Args:
            block: CodeBlock to check

        Returns:
            True if the block can be executed
        """
        return block.language in self.EXECUTABLE_LANGUAGES

    def is_validatable(self, block: CodeBlock) -> bool:
        """
        Check if a code block can be validated programmatically.

        Args:
            block: CodeBlock to check

        Returns:
            True if the block can be validated
        """
        return block.language in self.VALIDATABLE_LANGUAGES

    def filter_by_language(self, blocks: List[CodeBlock], language: str) -> List[CodeBlock]:
        """
        Filter code blocks by language.

        Args:
            blocks: List of CodeBlock objects
            language: Language to filter by

        Returns:
            Filtered list of CodeBlock objects
        """
        language = language.lower()
        return [b for b in blocks if b.language == language]

    def filter_executable(self, blocks: List[CodeBlock]) -> List[CodeBlock]:
        """
        Filter to only executable code blocks.

        Args:
            blocks: List of CodeBlock objects

        Returns:
            List of executable CodeBlock objects
        """
        return [b for b in blocks if self.is_executable(b)]

    def filter_validatable(self, blocks: List[CodeBlock]) -> List[CodeBlock]:
        """
        Filter to only validatable code blocks.

        Args:
            blocks: List of CodeBlock objects

        Returns:
            List of validatable CodeBlock objects
        """
        return [b for b in blocks if self.is_validatable(b)]

    def get_statistics(self, blocks: List[CodeBlock]) -> dict:
        """
        Get statistics about extracted code blocks.

        Args:
            blocks: List of CodeBlock objects

        Returns:
            Dictionary with statistics
        """
        languages = {}
        for block in blocks:
            languages[block.language] = languages.get(block.language, 0) + 1

        return {
            'total_blocks': len(blocks),
            'executable_blocks': len(self.filter_executable(blocks)),
            'validatable_blocks': len(self.filter_validatable(blocks)),
            'languages': languages,
            'total_lines': sum(len(b.code.splitlines()) for b in blocks),
        }


def main():
    """Command-line interface for snippet extraction."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description='Extract code blocks from markdown files')
    parser.add_argument('file', help='Markdown file to extract from')
    parser.add_argument('--language', '-l', help='Filter by language')
    parser.add_argument('--executable', '-e', action='store_true', help='Only executable blocks')
    parser.add_argument('--stats', '-s', action='store_true', help='Show statistics')
    parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    extractor = ReadmeSnippetExtractor()
    blocks = extractor.extract_code_blocks(args.file)

    if args.language:
        blocks = extractor.filter_by_language(blocks, args.language)

    if args.executable:
        blocks = extractor.filter_executable(blocks)

    if args.stats:
        stats = extractor.get_statistics(blocks)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Total blocks: {stats['total_blocks']}")
            print(f"Executable: {stats['executable_blocks']}")
            print(f"Validatable: {stats['validatable_blocks']}")
            print(f"Total lines: {stats['total_lines']}")
            print(f"Languages: {stats['languages']}")
        return

    if args.json:
        output = [
            {
                'language': b.language,
                'code': b.code,
                'line_number': b.line_number,
                'executable': extractor.is_executable(b),
                'validatable': extractor.is_validatable(b),
            }
            for b in blocks
        ]
        print(json.dumps(output, indent=2))
    else:
        for block in blocks:
            print(f"\n--- {block.language} (line {block.line_number}) ---")
            print(block.code)


if __name__ == '__main__':
    main()
