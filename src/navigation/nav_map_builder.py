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
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum

# Configure logging with [ITEM-BOOT-001] prefix
logger = logging.getLogger(__name__)


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


# =============================================================================
# ITEM-BOOT-001: Dependency Graph Schema
# =============================================================================

class NodeType(Enum):
    """Node types in the dependency graph."""
    FILE = "file"
    SYMBOL = "symbol"
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    VARIABLE = "variable"


class RelationType(Enum):
    """Relationship types between dependency graph nodes."""
    IMPORTS = "imports"           # Python import statements
    CALLS = "calls"               # Function/method calls
    DEPENDS_ON = "depends_on"     # General dependencies
    EXTENDS = "extends"           # Class inheritance
    IMPLEMENTS = "implements"     # Interface implementation
    REFERENCES = "references"     # Variable/constant references
    CONTAINS = "contains"         # Parent-child relationship


@dataclass
class DependencyNode:
    """
    ITEM-BOOT-001: A node in the dependency graph.
    
    Attributes:
        id: Unique identifier for the node
        type: Type of the node (file, symbol, module, etc.)
        name: Human-readable name
        location: Location in format file:line
        metadata: Additional metadata
    """
    id: str
    type: NodeType
    name: str
    location: str  # file:line format
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "location": self.location,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DependencyNode':
        """Create from dictionary."""
        return cls(
            id=data["id"],
            type=NodeType(data["type"]),
            name=data["name"],
            location=data["location"],
            metadata=data.get("metadata", {})
        )


@dataclass
class DependencyEdge:
    """
    ITEM-BOOT-001: An edge in the dependency graph.
    
    Attributes:
        from_id: Source node ID
        to_id: Target node ID
        relation: Type of relationship
        weight: Edge weight (default 1.0)
        metadata: Additional metadata
    """
    from_id: str
    to_id: str
    relation: RelationType
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "from": self.from_id,
            "to": self.to_id,
            "relation": self.relation.value,
            "weight": self.weight,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DependencyEdge':
        """Create from dictionary."""
        return cls(
            from_id=data["from"],
            to_id=data["to"],
            relation=RelationType(data["relation"]),
            weight=data.get("weight", 1.0),
            metadata=data.get("metadata", {})
        )


@dataclass
class DependencyCycle:
    """
    ITEM-BOOT-001: Detected dependency cycle.
    
    Attributes:
        cycle_id: Unique identifier for the cycle
        nodes: List of node IDs forming the cycle
        severity: Severity level (error, warning, info)
        description: Human-readable description
    """
    cycle_id: str
    nodes: List[str]
    severity: str  # "error", "warning", "info"
    description: str
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "cycle_id": self.cycle_id,
            "nodes": self.nodes,
            "severity": self.severity,
            "description": self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DependencyCycle':
        """Create from dictionary."""
        return cls(
            cycle_id=data["cycle_id"],
            nodes=data["nodes"],
            severity=data["severity"],
            description=data["description"]
        )


@dataclass
class DependencyGraph:
    """
    ITEM-BOOT-001: Complete dependency graph with cycle detection.
    
    DEPENDENCY_GRAPH_SCHEMA:
    - nodes: [{id, type, location}]
    - edges: [{from, to, relation}]
    - metadata: {cycle_detected, topological_order}
    
    Attributes:
        nodes: Dictionary of node ID to DependencyNode
        edges: List of DependencyEdge
        metadata: Graph metadata
        cycles: List of detected cycles
        topological_order: Topological ordering of nodes
    """
    nodes: Dict[str, DependencyNode]
    edges: List[DependencyEdge]
    metadata: Dict[str, Any]
    cycles: List[DependencyCycle]
    topological_order: List[str]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "metadata": self.metadata,
            "cycles": [c.to_dict() for c in self.cycles],
            "topological_order": self.topological_order
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'DependencyGraph':
        """Create from dictionary."""
        nodes = {n["id"]: DependencyNode.from_dict(n) for n in data.get("nodes", [])}
        edges = [DependencyEdge.from_dict(e) for e in data.get("edges", [])]
        cycles = [DependencyCycle.from_dict(c) for c in data.get("cycles", [])]
        
        return cls(
            nodes=nodes,
            edges=edges,
            metadata=data.get("metadata", {}),
            cycles=cycles,
            topological_order=data.get("topological_order", [])
        )
    
    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'DependencyGraph':
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


class DependencyGraphBuilder:
    """
    ITEM-BOOT-001: Build complete dependency graph with cycle detection.
    
    Builds DEPENDENCY_GRAPH_SCHEMA with:
    - nodes: [{id, type, location}]
    - edges: [{from, to, relation}]
    - metadata: {cycle_detected, topological_order}
    
    Features:
    - Multi-language support (Python, JavaScript)
    - Import extraction
    - Function call extraction
    - Cycle detection using DFS
    - Topological sorting
    
    Example:
        builder = DependencyGraphBuilder()
        graph = builder.build_dependency_graph(
            files=["main.py", "utils.py"],
            content_map={"main.py": "...", "utils.py": "..."}
        )
        
        if graph.cycles:
            print(f"Warning: {len(graph.cycles)} cycles detected")
        
        for node_id in graph.topological_order:
            print(f"Process: {node_id}")
    """
    
    # Patterns for dependency extraction by language
    IMPORT_PATTERNS = {
        "python": [
            (r'^import\s+(\w+)', RelationType.IMPORTS),
            (r'^from\s+(\w+)\s+import', RelationType.IMPORTS),
            (r'^from\s+(\w+(?:\.\w+)*)\s+import', RelationType.IMPORTS),
        ],
        "javascript": [
            (r'import\s+.*\s+from\s+[\'"]([^\'"]+)[\'"]', RelationType.IMPORTS),
            (r'require\([\'"]([^\'"]+)[\'"]\)', RelationType.IMPORTS),
        ]
    }
    
    CALL_PATTERNS = {
        "python": [
            (r'(\w+)\s*\(', RelationType.CALLS),
        ],
        "javascript": [
            (r'(\w+)\s*\(', RelationType.CALLS),
        ]
    }
    
    CLASS_PATTERNS = {
        "python": [
            (r'class\s+(\w+)\s*\(([^)]*)\)', 'extends_check'),
        ],
        "javascript": [
            (r'class\s+(\w+)\s+extends\s+(\w+)', RelationType.EXTENDS),
        ]
    }
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the dependency graph builder.
        
        Args:
            config: Optional configuration dictionary
        """
        self._config = config or {}
        self._nodes: Dict[str, DependencyNode] = {}
        self._edges: List[DependencyEdge] = []
        self._adjacency: Dict[str, Set[str]] = {}
        self._reverse_adjacency: Dict[str, Set[str]] = {}
        
        logger.debug("[ITEM-BOOT-001] DependencyGraphBuilder initialized")
    
    def build_dependency_graph(self, files: List[str], 
                               content_map: Dict[str, str]) -> DependencyGraph:
        """
        Build dependency graph from files and their content.
        
        Args:
            files: List of file paths
            content_map: Dictionary mapping file paths to content
            
        Returns:
            DependencyGraph with nodes, edges, cycles, and topological order
        """
        logger.info(f"[ITEM-BOOT-001] Building dependency graph for {len(files)} files")
        
        # Step 1: Create file nodes
        for filepath in files:
            self._add_file_node(filepath)
        
        # Step 2: Extract dependencies from content
        for filepath, content in content_map.items():
            self._extract_dependencies(filepath, content)
        
        # Step 3: Detect cycles
        cycles = self._detect_cycles()
        if cycles:
            logger.warning(f"[ITEM-BOOT-001] Detected {len(cycles)} dependency cycles")
        
        # Step 4: Compute topological order
        topo_order = self._topological_sort()
        logger.info(f"[ITEM-BOOT-001] Computed topological order for {len(topo_order)} nodes")
        
        # Build metadata
        metadata = {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "files_analyzed": len(files),
            "cycle_detected": len(cycles) > 0,
            "cycle_count": len(cycles),
            "builder_version": "5.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }
        
        return DependencyGraph(
            nodes=dict(self._nodes),
            edges=list(self._edges),
            metadata=metadata,
            cycles=cycles,
            topological_order=topo_order
        )
    
    def build_from_directory(self, directory: str, 
                            extensions: Optional[List[str]] = None) -> DependencyGraph:
        """
        Build dependency graph from all files in a directory.
        
        Args:
            directory: Directory path to scan
            extensions: File extensions to include (default: .py, .js, .ts)
            
        Returns:
            DependencyGraph with nodes, edges, cycles, and topological order
        """
        if extensions is None:
            extensions = ['.py', '.js', '.ts', '.jsx', '.tsx']
        
        dir_path = Path(directory)
        files = []
        content_map = {}
        
        for ext in extensions:
            for filepath in dir_path.rglob(f'*{ext}'):
                # Skip hidden directories and common exclusions
                if any(part.startswith('.') or part in ['node_modules', '__pycache__', 'venv', 'env'] 
                       for part in filepath.parts):
                    continue
                
                try:
                    content = filepath.read_text(encoding='utf-8')
                    files.append(str(filepath))
                    content_map[str(filepath)] = content
                except Exception as e:
                    logger.warning(f"[ITEM-BOOT-001] Could not read {filepath}: {e}")
        
        return self.build_dependency_graph(files, content_map)
    
    def _add_file_node(self, filepath: str) -> DependencyNode:
        """Add a file node to the graph."""
        node_id = self._generate_node_id(filepath, NodeType.FILE)
        node = DependencyNode(
            id=node_id,
            type=NodeType.FILE,
            name=Path(filepath).name,
            location=filepath,
            metadata={"path": filepath}
        )
        self._nodes[node_id] = node
        logger.debug(f"[ITEM-BOOT-001] Added file node: {node_id}")
        return node
    
    def _add_symbol_node(self, name: str, symbol_type: NodeType, 
                         filepath: str, line: int) -> DependencyNode:
        """Add a symbol node to the graph."""
        node_id = self._generate_node_id(name, symbol_type)
        if node_id not in self._nodes:
            node = DependencyNode(
                id=node_id,
                type=symbol_type,
                name=name,
                location=f"{filepath}:{line}",
                metadata={"file": filepath, "line": line}
            )
            self._nodes[node_id] = node
        return self._nodes[node_id]
    
    def _extract_dependencies(self, filepath: str, content: str):
        """Extract dependencies from file content."""
        lines = content.split('\n')
        file_node_id = self._generate_node_id(filepath, NodeType.FILE)
        
        # Detect language
        lang = self._detect_language(filepath, content)
        logger.debug(f"[ITEM-BOOT-001] Detected language {lang} for {filepath}")
        
        # Extract imports
        self._extract_imports(filepath, content, lang, file_node_id)
        
        # Extract class definitions and inheritance
        self._extract_class_relations(filepath, content, lang, file_node_id, lines)
        
        # Extract function calls
        self._extract_calls(filepath, content, lang, file_node_id)
    
    def _extract_imports(self, filepath: str, content: str, 
                        lang: str, file_node_id: str):
        """Extract import statements."""
        patterns = self.IMPORT_PATTERNS.get(lang, [])
        
        for line_num, line in enumerate(content.split('\n'), 1):
            for pattern, relation in patterns:
                for match in re.finditer(pattern, line):
                    imported = match.group(1)
                    imported_id = self._generate_node_id(imported, NodeType.MODULE)
                    
                    # Create module node if not exists
                    if imported_id not in self._nodes:
                        self._nodes[imported_id] = DependencyNode(
                            id=imported_id,
                            type=NodeType.MODULE,
                            name=imported,
                            location=imported,
                            metadata={"imported_from": filepath}
                        )
                    
                    # Add edge
                    self._add_edge(file_node_id, imported_id, relation, 
                                  {"line": line_num, "statement": line.strip()})
    
    def _extract_class_relations(self, filepath: str, content: str, 
                                 lang: str, file_node_id: str, lines: List[str]):
        """Extract class definitions and inheritance."""
        if lang == "python":
            for line_num, line in enumerate(lines, 1):
                # Match class definition with inheritance
                match = re.match(r'class\s+(\w+)\s*\(([^)]*)\)', line)
                if match:
                    class_name = match.group(1)
                    base_classes = match.group(2).strip()
                    
                    # Add class node
                    class_id = self._add_symbol_node(
                        class_name, NodeType.CLASS, filepath, line_num
                    )
                    
                    # Add contains edge from file to class
                    self._add_edge(file_node_id, class_id.id, RelationType.CONTAINS,
                                  {"line": line_num})
                    
                    # Process base classes
                    if base_classes:
                        for base in base_classes.split(','):
                            base = base.strip()
                            if base and base not in ['object', 'ABC']:
                                base_id = self._generate_node_id(base, NodeType.CLASS)
                                
                                # Create base class node if not exists
                                if base_id not in self._nodes:
                                    self._nodes[base_id] = DependencyNode(
                                        id=base_id,
                                        type=NodeType.CLASS,
                                        name=base,
                                        location=f"external:{base}",
                                        metadata={"external": True}
                                    )
                                
                                self._add_edge(class_id.id, base_id, RelationType.EXTENDS,
                                              {"line": line_num})
        
        elif lang == "javascript":
            for line_num, line in enumerate(lines, 1):
                match = re.search(r'class\s+(\w+)\s+extends\s+(\w+)', line)
                if match:
                    class_name = match.group(1)
                    base_class = match.group(2)
                    
                    class_id = self._add_symbol_node(
                        class_name, NodeType.CLASS, filepath, line_num
                    )
                    base_id = self._generate_node_id(base_class, NodeType.CLASS)
                    
                    if base_id not in self._nodes:
                        self._nodes[base_id] = DependencyNode(
                            id=base_id,
                            type=NodeType.CLASS,
                            name=base_class,
                            location=f"external:{base_class}",
                            metadata={"external": True}
                        )
                    
                    self._add_edge(class_id.id, base_id, RelationType.EXTENDS,
                                  {"line": line_num})
    
    def _extract_calls(self, filepath: str, content: str, 
                      lang: str, file_node_id: str):
        """Extract function calls (simplified)."""
        # Note: This is a simplified implementation
        # A full implementation would use AST parsing
        patterns = self.CALL_PATTERNS.get(lang, [])
        
        for line_num, line in enumerate(content.split('\n'), 1):
            # Skip comments and strings
            if lang == "python" and (line.strip().startswith('#') or 
                                     line.strip().startswith('"""') or
                                     line.strip().startswith("'''")):
                continue
            
            for pattern, relation in patterns:
                for match in re.finditer(pattern, line):
                    func_name = match.group(1)
                    # Skip common builtins and keywords
                    if func_name in ['if', 'for', 'while', 'with', 'except', 'print',
                                    'len', 'range', 'str', 'int', 'list', 'dict',
                                    'set', 'tuple', 'open', 'type', 'isinstance']:
                        continue
                    
                    func_id = self._generate_node_id(func_name, NodeType.FUNCTION)
                    
                    # Create function node if not exists
                    if func_id not in self._nodes:
                        self._nodes[func_id] = DependencyNode(
                            id=func_id,
                            type=NodeType.FUNCTION,
                            name=func_name,
                            location=f"unknown:{func_name}",
                            metadata={"callsite": filepath, "line": line_num}
                        )
                    
                    # Add call edge
                    self._add_edge(file_node_id, func_id, RelationType.CALLS,
                                  {"line": line_num})
    
    def _add_edge(self, from_id: str, to_id: str, relation: RelationType, 
                  metadata: Optional[Dict] = None):
        """Add an edge to the graph."""
        edge = DependencyEdge(
            from_id=from_id,
            to_id=to_id,
            relation=relation,
            metadata=metadata or {}
        )
        self._edges.append(edge)
        
        # Update adjacency lists
        if from_id not in self._adjacency:
            self._adjacency[from_id] = set()
        self._adjacency[from_id].add(to_id)
        
        if to_id not in self._reverse_adjacency:
            self._reverse_adjacency[to_id] = set()
        self._reverse_adjacency[to_id].add(from_id)
    
    def _detect_cycles(self) -> List[DependencyCycle]:
        """
        Detect all cycles in the dependency graph using DFS.
        
        Returns:
            List of DependencyCycle objects
        """
        cycles = []
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self._adjacency.get(node, set()):
                if neighbor not in visited:
                    cycle = dfs(neighbor)
                    if cycle:
                        return cycle
                elif neighbor in rec_stack:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    return path[cycle_start:] + [neighbor]
            
            path.pop()
            rec_stack.remove(node)
            return None
        
        for node in list(self._nodes.keys()):
            if node not in visited:
                cycle_path = dfs(node)
                if cycle_path:
                    cycles.append(DependencyCycle(
                        cycle_id=f"CYCLE-{len(cycles)+1}",
                        nodes=cycle_path,
                        severity="warning",
                        description=f"Circular dependency: {' -> '.join(cycle_path)}"
                    ))
                    # Reset for finding more cycles
                    visited.clear()
                    rec_stack.clear()
                    path.clear()
        
        return cycles
    
    def _topological_sort(self) -> List[str]:
        """
        Compute topological order of nodes using Kahn's algorithm.
        
        Returns:
            List of node IDs in topological order
        """
        # Calculate in-degree for each node
        in_degree = {n: 0 for n in self._nodes}
        
        for edge in self._edges:
            if edge.to_id in in_degree:
                in_degree[edge.to_id] += 1
        
        # Start with nodes having no incoming edges
        queue = [n for n, d in in_degree.items() if d == 0]
        result = []
        
        while queue:
            # Sort for deterministic output
            queue.sort()
            node = queue.pop(0)
            result.append(node)
            
            for neighbor in self._adjacency.get(node, set()):
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)
        
        # If not all nodes processed, there's a cycle
        if len(result) != len(self._nodes):
            # Return partial order with remaining nodes appended
            remaining = [n for n in self._nodes if n not in result]
            remaining.sort()  # Sort for determinism
            result.extend(remaining)
            logger.warning(
                f"[ITEM-BOOT-001] Topological sort incomplete: "
                f"{len(result) - len(remaining)} of {len(self._nodes)} nodes ordered"
            )
        
        return result
    
    def _generate_node_id(self, name: str, node_type: NodeType) -> str:
        """Generate unique node ID."""
        return f"{node_type.value}:{name}"
    
    def _detect_language(self, filepath: str, content: str) -> str:
        """Detect programming language from file extension."""
        if filepath.endswith('.py'):
            return 'python'
        elif filepath.endswith(('.js', '.jsx')):
            return 'javascript'
        elif filepath.endswith(('.ts', '.tsx')):
            return 'javascript'  # TypeScript uses similar patterns
        return 'python'  # Default
    
    def get_node(self, node_id: str) -> Optional[DependencyNode]:
        """Get a node by ID."""
        return self._nodes.get(node_id)
    
    def get_neighbors(self, node_id: str) -> Set[str]:
        """Get neighbors of a node."""
        return self._adjacency.get(node_id, set())
    
    def get_predecessors(self, node_id: str) -> Set[str]:
        """Get predecessors of a node."""
        return self._reverse_adjacency.get(node_id, set())


def create_nav_map_builder(config: Optional[Dict] = None) -> NavMapBuilder:
    """
    Factory function to create NavMapBuilder.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured NavMapBuilder instance
    """
    return NavMapBuilder(config=config)


def create_dependency_graph_builder(config: Optional[Dict] = None) -> DependencyGraphBuilder:
    """
    ITEM-BOOT-001: Factory function to create DependencyGraphBuilder.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        Configured DependencyGraphBuilder instance
    """
    return DependencyGraphBuilder(config=config)
