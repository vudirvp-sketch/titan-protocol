#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Navigation Map Builder

Implements Step 0.3: Build Navigation Map from PROTOCOL.md:

ACTIONS:
  - Chunk file (1000–1500 lines per block; enforce PRINCIPLE-04 secondary limits)
  - Assign IDs: [C1], [C2], ...
  - Extract:
    - Headings tree (H1-H6)
    - Code blocks
    - Tables
    - Checklists
  - Build NAV_MAP:
      section → chunk_id → line_range

OUTPUT:
  - TOC (normalized)
  - Chunk index
  - Cross-ref graph

Also implements PRINCIPLE-04:
  Primary limit:   1000–1500 lines per chunk
                   Reduce to 500–800 lines for files > 30k lines
  Secondary limits (hard caps):
    max_chars_per_chunk:  150_000 characters
    max_tokens_per_chunk: 30_000 tokens

Usage:
    from src.navigation import NavMapBuilder
    
    builder = NavMapBuilder(config)
    nav_map = builder.build(content)
    
    print(f"Total chunks: {len(nav_map.chunks)}")
    print(f"TOC entries: {len(nav_map.toc)}")
    
    # Get chunk for a section
    chunk = nav_map.get_chunk_for_section("Introduction")
"""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


class ChunkStatus(Enum):
    """Status of a chunk during processing."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass
class Chunk:
    """
    Represents a chunk of the document.
    
    Per-chunk metadata from PROTOCOL.md:
    ├─ chunk_id: [C1], [C2], ...
    ├─ status: PENDING | IN_PROGRESS | COMPLETE | FAILED
    ├─ changes: list of applied modifications
    └─ offset: Δline_numbers after modifications
    """
    chunk_id: str
    line_start: int
    line_end: int
    status: ChunkStatus = ChunkStatus.PENDING
    char_count: int = 0
    token_estimate: int = 0
    headings: List[str] = field(default_factory=list)
    code_blocks: int = 0
    tables: int = 0
    checklists: int = 0
    changes: List[Dict] = field(default_factory=list)
    offset: int = 0
    checksum: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "chunk_id": self.chunk_id,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "status": self.status.value,
            "char_count": self.char_count,
            "token_estimate": self.token_estimate,
            "headings": self.headings,
            "code_blocks": self.code_blocks,
            "tables": self.tables,
            "checklists": self.checklists,
            "offset": self.offset,
            "checksum": self.checksum
        }


@dataclass
class TOCEntry:
    """Table of contents entry."""
    level: int
    text: str
    line: int
    chunk_id: str
    anchor: Optional[str] = None
    children: List['TOCEntry'] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "level": self.level,
            "text": self.text,
            "line": self.line,
            "chunk_id": self.chunk_id,
            "anchor": self.anchor,
            "children": [c.to_dict() for c in self.children]
        }


@dataclass
class NavMap:
    """
    Navigation map for a document.
    
    Implements NAV_MAP from PROTOCOL.md:
    section → chunk_id → line_range
    """
    chunks: Dict[str, Chunk] = field(default_factory=dict)
    toc: List[TOCEntry] = field(default_factory=list)
    section_to_chunk: Dict[str, str] = field(default_factory=dict)
    cross_refs: Dict[str, List[str]] = field(default_factory=dict)
    total_lines: int = 0
    total_chars: int = 0
    total_tokens_estimate: int = 0
    
    def get_chunk_for_section(self, section_name: str) -> Optional[Chunk]:
        """Get the chunk containing a section."""
        chunk_id = self.section_to_chunk.get(section_name)
        if chunk_id:
            return self.chunks.get(chunk_id)
        return None
    
    def get_chunk_for_line(self, line_number: int) -> Optional[Chunk]:
        """Get the chunk containing a specific line."""
        for chunk in self.chunks.values():
            if chunk.line_start <= line_number <= chunk.line_end:
                return chunk
        return None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "chunks": {k: v.to_dict() for k, v in self.chunks.items()},
            "toc": [e.to_dict() for e in self.toc],
            "section_to_chunk": self.section_to_chunk,
            "cross_refs": self.cross_refs,
            "total_lines": self.total_lines,
            "total_chars": self.total_chars,
            "total_tokens_estimate": self.total_tokens_estimate
        }


class NavMapBuilder:
    """
    Navigation Map Builder with semantic boundary detection.
    
    Implements:
    - Chunking with PRINCIPLE-04 limits
    - Semantic boundary detection
    - TOC extraction
    - Cross-reference graph building
    
    Example:
        builder = NavMapBuilder(config)
        
        # Build from file
        nav_map = builder.build_from_file("document.md")
        
        # Build from content
        nav_map = builder.build(content, filename="document.md")
        
        # Access chunks
        for chunk_id, chunk in nav_map.chunks.items():
            print(f"{chunk_id}: L{chunk.line_start}-L{chunk.line_end}")
    """
    
    # Token estimation constants
    CHARS_PER_TOKEN = 4
    WORDS_PER_TOKEN = 1.3
    
    # Semantic boundary markers
    BOUNDARY_MARKERS = [
        r'^#{1,6}\s+',  # Headings
        r'^---+$',  # Horizontal rules
        r'^```',  # Code block starts
        r'^\*\*\*+$',  # Alternative horizontal rules
        r'^<\w+[^>]*>$',  # HTML opening tags
        r'^</\w+>$',  # HTML closing tags
    ]
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize the navigation map builder."""
        self.config = config or {}
        
        # Chunking limits from config
        chunking = self.config.get("chunking", {})
        limits = self.config.get("chunking_limits", {})
        
        self.default_chunk_size = chunking.get("default_size", 1500)
        self.large_file_chunk_size = chunking.get("large_file_size", 800)
        self.large_file_threshold = 30000  # lines
        
        # Secondary limits (PRINCIPLE-04)
        self.max_chars_per_chunk = limits.get("max_chars_per_chunk", 150000)
        self.max_tokens_per_chunk = limits.get("max_tokens_per_chunk", 30000)
        self.enforce_secondary_limits = limits.get("enforce_secondary_limits", True)
    
    def build(self, content: str, filename: str = "unknown") -> NavMap:
        """
        Build navigation map from content.
        
        Args:
            content: Document content
            filename: Filename for context
            
        Returns:
            NavMap with chunks, TOC, and cross-references
        """
        lines = content.split('\n')
        total_lines = len(lines)
        total_chars = len(content)
        
        nav_map = NavMap(
            total_lines=total_lines,
            total_chars=total_chars,
            total_tokens_estimate=self._estimate_tokens(content)
        )
        
        # Determine chunk size based on file size
        chunk_size = self._get_chunk_size(total_lines)
        
        # Extract TOC (headings)
        nav_map.toc = self._extract_toc(lines)
        
        # Find semantic boundaries
        boundaries = self._find_semantic_boundaries(lines)
        
        # Create chunks
        chunks = self._create_chunks(lines, boundaries, chunk_size)
        
        for chunk in chunks:
            nav_map.chunks[chunk.chunk_id] = chunk
        
        # Build section to chunk mapping
        for entry in nav_map.toc:
            chunk = nav_map.get_chunk_for_line(entry.line)
            if chunk:
                nav_map.section_to_chunk[entry.text] = chunk.chunk_id
        
        # Extract cross-references
        nav_map.cross_refs = self._extract_cross_refs(content, nav_map.chunks)
        
        return nav_map
    
    def build_from_file(self, filepath: str) -> NavMap:
        """
        Build navigation map from file.
        
        Args:
            filepath: Path to file
            
        Returns:
            NavMap with chunks, TOC, and cross-references
        """
        path = Path(filepath)
        
        with open(path) as f:
            content = f.read()
        
        nav_map = self.build(content, filename=path.name)
        
        # Calculate checksums for chunks
        lines = content.split('\n')
        for chunk in nav_map.chunks.values():
            chunk_content = '\n'.join(lines[chunk.line_start:chunk.line_end])
            chunk.checksum = hashlib.sha256(chunk_content.encode()).hexdigest()[:16]
        
        return nav_map
    
    def _get_chunk_size(self, total_lines: int) -> int:
        """Determine chunk size based on file size."""
        if total_lines > self.large_file_threshold:
            return self.large_file_chunk_size
        return self.default_chunk_size
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        word_count = len(text.split())
        return int(word_count * self.WORDS_PER_TOKEN)
    
    def _find_semantic_boundaries(self, lines: List[str]) -> List[int]:
        """
        Find semantic boundary lines.
        
        Boundaries are at:
        - Headings
        - Code block starts/ends
        - Horizontal rules
        - Empty lines after paragraphs (partial)
        """
        boundaries = []
        
        compiled_patterns = [re.compile(p) for p in self.BOUNDARY_MARKERS]
        
        for i, line in enumerate(lines):
            for pattern in compiled_patterns:
                if pattern.match(line):
                    boundaries.append(i)
                    break
        
        # Also add empty lines that follow content (paragraph breaks)
        prev_has_content = False
        for i, line in enumerate(lines):
            has_content = bool(line.strip())
            if not has_content and prev_has_content:
                # Empty line after content - potential boundary
                if i not in boundaries:
                    boundaries.append(i)
            prev_has_content = has_content
        
        return sorted(set(boundaries))
    
    def _create_chunks(self, lines: List[str], 
                       boundaries: List[int],
                       target_size: int) -> List[Chunk]:
        """
        Create chunks respecting semantic boundaries.
        
        Uses boundaries to split at natural document divisions.
        """
        chunks = []
        total_lines = len(lines)
        
        chunk_start = 0
        chunk_id_counter = 1
        
        while chunk_start < total_lines:
            # Target end line
            target_end = min(chunk_start + target_size, total_lines)
            
            # Find best boundary near target
            chunk_end = self._find_best_boundary(
                boundaries, 
                target_end, 
                chunk_start,
                total_lines
            )
            
            # Create chunk
            chunk_lines = lines[chunk_start:chunk_end]
            chunk_content = '\n'.join(chunk_lines)
            
            # Check secondary limits
            if self.enforce_secondary_limits:
                char_count = len(chunk_content)
                token_estimate = self._estimate_tokens(chunk_content)
                
                # If over limits, split further
                if (char_count > self.max_chars_per_chunk or 
                    token_estimate > self.max_tokens_per_chunk):
                    # Reduce chunk size
                    reduced_end = self._reduce_to_limits(
                        lines, chunk_start, chunk_end
                    )
                    chunk_end = reduced_end
                    chunk_lines = lines[chunk_start:chunk_end]
                    chunk_content = '\n'.join(chunk_lines)
            
            # Extract chunk metadata
            chunk = Chunk(
                chunk_id=f"C{chunk_id_counter}",
                line_start=chunk_start,
                line_end=chunk_end,
                char_count=len(chunk_content),
                token_estimate=self._estimate_tokens(chunk_content),
                headings=self._extract_headings(chunk_lines),
                code_blocks=self._count_code_blocks(chunk_lines),
                tables=self._count_tables(chunk_lines),
                checklists=self._count_checklists(chunk_lines)
            )
            
            chunks.append(chunk)
            
            chunk_start = chunk_end
            chunk_id_counter += 1
        
        return chunks
    
    def _find_best_boundary(self, boundaries: List[int], 
                           target: int, 
                           minimum: int,
                           maximum: int) -> int:
        """Find the best boundary near the target."""
        if not boundaries:
            return target
        
        # Filter boundaries in valid range
        valid_boundaries = [b for b in boundaries if minimum < b < maximum]
        
        if not valid_boundaries:
            return target
        
        # Find closest boundary to target
        closest = min(valid_boundaries, key=lambda b: abs(b - target))
        
        # Only use if within 20% of target
        tolerance = int(maximum * 0.2)
        if abs(closest - target) <= tolerance:
            return closest
        
        return target
    
    def _reduce_to_limits(self, lines: List[str], 
                         start: int, 
                         end: int) -> int:
        """Reduce chunk to fit within secondary limits."""
        # Binary search for the right size
        low = start
        high = end
        
        while low < high:
            mid = (low + high + 1) // 2
            chunk_content = '\n'.join(lines[start:mid])
            
            char_count = len(chunk_content)
            token_estimate = self._estimate_tokens(chunk_content)
            
            if (char_count <= self.max_chars_per_chunk and 
                token_estimate <= self.max_tokens_per_chunk):
                low = mid
            else:
                high = mid - 1
        
        return low
    
    def _extract_toc(self, lines: List[str]) -> List[TOCEntry]:
        """Extract table of contents from headings."""
        toc = []
        
        for i, line in enumerate(lines):
            match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                
                # Generate anchor
                anchor = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
                
                # For now, flat list (would build tree in full impl)
                toc.append(TOCEntry(
                    level=level,
                    text=text,
                    line=i,
                    chunk_id="",  # Filled in later
                    anchor=anchor
                ))
        
        return toc
    
    def _extract_headings(self, lines: List[str]) -> List[str]:
        """Extract heading texts from lines."""
        headings = []
        for line in lines:
            match = re.match(r'^#{1,6}\s+(.+)$', line)
            if match:
                headings.append(match.group(1).strip())
        return headings
    
    def _count_code_blocks(self, lines: List[str]) -> int:
        """Count code blocks in lines."""
        count = 0
        for line in lines:
            if line.strip().startswith('```'):
                count += 1
        return count // 2  # Each block has start and end
    
    def _count_tables(self, lines: List[str]) -> int:
        """Count tables in lines (simple heuristic)."""
        count = 0
        in_table = False
        
        for line in lines:
            if '|' in line and line.count('|') >= 2:
                if not in_table:
                    count += 1
                    in_table = True
            else:
                in_table = False
        
        return count
    
    def _count_checklists(self, lines: List[str]) -> int:
        """Count checklist items in lines."""
        count = 0
        for line in lines:
            if re.match(r'^\s*[-*]\s+\[[ x]\]', line):
                count += 1
        return count
    
    def _extract_cross_refs(self, content: str, 
                           chunks: Dict[str, Chunk]) -> Dict[str, List[str]]:
        """
        Extract cross-references between chunks.
        
        Format: {chunk_id: [referenced_chunk_ids]}
        """
        refs = defaultdict(list)
        
        # Find all [text](#anchor) references
        anchor_refs = re.findall(r'\[[^\]]+\]\(#([^)]+)\)', content)
        
        # Map anchors to chunks
        anchor_to_chunk = {}
        for chunk_id, chunk in chunks.items():
            # Check each heading in chunk
            for heading in chunk.headings:
                anchor = re.sub(r'[^a-z0-9]+', '-', heading.lower()).strip('-')
                anchor_to_chunk[anchor] = chunk_id
        
        # Build reference graph
        for anchor in anchor_refs:
            if anchor in anchor_to_chunk:
                target_chunk = anchor_to_chunk[anchor]
                # Find source chunk (would need line-by-line analysis)
                # For now, just note the reference exists
                pass
        
        # Find all [text](file.md) references
        file_refs = re.findall(r'\[[^\]]+\]\(([^)#)]+\.md)\)', content)
        
        return dict(refs)


def create_nav_map_builder(config: Optional[Dict] = None) -> NavMapBuilder:
    """
    Factory function to create NavMapBuilder.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured NavMapBuilder instance
    """
    return NavMapBuilder(config=config)
