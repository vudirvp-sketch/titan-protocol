#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Context Graph Builder

ITEM-SAE-003: Context Graph Generation Integration

Extends NavMapBuilder to generate context_graph.json alongside nav_map.json.
Builds a trust-aware context graph from codebase analysis.

Features:
- File node extraction with trust scoring
- Dependency edge extraction
- Version vector initialization
- Semantic hash computation
- Integration with NavMapBuilder

Output:
  - .ai/context_graph.json with nodes, edges, and metadata

Author: TITAN FUSE Team
Version: 1.0.0
"""

import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class NodeType(Enum):
    """Type of context node."""
    FILE = "file"
    SYMBOL = "symbol"
    MODULE = "module"
    CONFIG = "config"
    CHECKPOINT = "checkpoint"
    ARTIFACT = "artifact"


class EdgeRelation(Enum):
    """Type of relationship between nodes."""
    IMPORTS = "imports"
    CALLS = "calls"
    DEPENDS_ON = "depends_on"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    REFERENCES = "references"
    CONTAINS = "contains"
    PRODUCES = "produces"


@dataclass
class NodeInfo:
    """Information about a context node."""
    id: str
    type: NodeType
    location: str
    content_hash: Optional[str] = None
    semantic_hash: Optional[str] = None
    trust_score: float = 0.5
    line_count: int = 0
    language: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeInfo:
    """Information about a context edge."""
    from_id: str
    to_id: str
    relation: EdgeRelation
    weight: float = 1.0
    line_number: Optional[int] = None


class ContextGraphBuilder:
    """
    Builds context graph from codebase analysis.
    
    Generates context_graph.json with:
    - Nodes for files, symbols, modules, configs
    - Edges for dependencies, imports, calls
    - Trust scores based on file characteristics
    - Version vectors for change tracking
    
    Usage:
        builder = ContextGraphBuilder(root_path=".")
        graph = builder.build()
        builder.save(graph, ".ai/context_graph.json")
    """
    
    # File patterns to analyze
    SOURCE_EXTENSIONS = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.jsx': 'javascript',
        '.tsx': 'typescript',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.md': 'markdown',
    }
    
    # Trust score modifiers
    TRUST_MODIFIERS = {
        'test_file': -0.1,       # Test files have lower base trust
        'config_file': 0.2,       # Config files are more trusted
        'core_module': 0.15,      # Core modules are more trusted
        'generated': -0.2,        # Generated code has lower trust
        'documentation': 0.1,     # Documentation has good trust
    }
    
    # Core module patterns (higher trust)
    CORE_PATTERNS = [
        r'src/core/',
        r'src/engine/',
        r'src/protocol/',
        r'src/validation/',
        r'src/context/',
    ]
    
    # Import patterns by language
    IMPORT_PATTERNS = {
        'python': [
            (r'^import\s+(\w+)', 'module'),
            (r'^from\s+(\w+(?:\.\w+)*)\s+import', 'module'),
        ],
        'javascript': [
            (r'import\s+.*\s+from\s+[\'"]([^\'"]+)[\'"]', 'module'),
            (r'require\([\'"]([^\'"]+)[\'"]\)', 'module'),
        ],
        'typescript': [
            (r'import\s+.*\s+from\s+[\'"]([^\'"]+)[\'"]', 'module'),
            (r'require\([\'"]([^\'"]+)[\'"]\)', 'module'),
        ],
    }
    
    def __init__(
        self,
        root_path: str = ".",
        exclude_dirs: Optional[List[str]] = None,
        max_file_size_mb: float = 5.0,
    ):
        """
        Initialize ContextGraphBuilder.
        
        Args:
            root_path: Root directory to analyze
            exclude_dirs: Directories to exclude from analysis
            max_file_size_mb: Maximum file size to process (in MB)
        """
        self._root_path = Path(root_path).resolve()
        self._exclude_dirs = set(exclude_dirs or [
            'node_modules', '__pycache__', '.git', 'venv', 'env',
            '.venv', 'build', 'dist', '.tox', '.eggs', 'eggs',
            '*.egg-info', '.mypy_cache', '.pytest_cache',
        ])
        self._max_file_size = int(max_file_size_mb * 1024 * 1024)
        
        self._nodes: Dict[str, NodeInfo] = {}
        self._edges: List[EdgeInfo] = []
        self._import_graph: Dict[str, Set[str]] = defaultdict(set)
        
        logger.info(f"[ContextGraphBuilder] Initialized for {self._root_path}")
    
    def build(self) -> Dict[str, Any]:
        """
        Build complete context graph.
        
        Returns:
            Dictionary containing context graph data
        """
        logger.info("[ContextGraphBuilder] Starting context graph build")
        
        # Reset state
        self._nodes.clear()
        self._edges.clear()
        self._import_graph.clear()
        
        # Phase 1: Collect all files as nodes
        self._collect_file_nodes()
        
        # Phase 2: Analyze dependencies
        self._analyze_dependencies()
        
        # Phase 3: Calculate trust scores
        self._calculate_trust_scores()
        
        # Phase 4: Build edges
        self._build_edges()
        
        # Generate output
        graph = self._generate_output()
        
        logger.info(
            f"[ContextGraphBuilder] Built graph with "
            f"{len(self._nodes)} nodes and {len(self._edges)} edges"
        )
        
        return graph
    
    def _collect_file_nodes(self) -> None:
        """Collect all files as context nodes."""
        for filepath in self._walk_files():
            try:
                node = self._create_file_node(filepath)
                if node:
                    self._nodes[node.id] = node
            except Exception as e:
                logger.warning(f"Failed to process {filepath}: {e}")
    
    def _walk_files(self) -> List[Path]:
        """Walk directory tree and collect files to analyze."""
        files = []
        
        for path in self._root_path.rglob('*'):
            # Skip excluded directories
            if any(part in self._exclude_dirs for part in path.parts):
                continue
            
            # Skip directories
            if path.is_dir():
                continue
            
            # Check file size
            try:
                if path.stat().st_size > self._max_file_size:
                    continue
            except OSError:
                continue
            
            # Check extension
            ext = path.suffix.lower()
            if ext in self.SOURCE_EXTENSIONS or path.name.startswith('.'):
                files.append(path)
        
        return files
    
    def _create_file_node(self, filepath: Path) -> Optional[NodeInfo]:
        """Create a node for a file."""
        # Determine node type
        ext = filepath.suffix.lower()
        language = self.SOURCE_EXTENSIONS.get(ext, 'unknown')
        
        # Determine file type
        if ext in ('.json', '.yaml', '.yml', '.toml'):
            node_type = NodeType.CONFIG
        elif ext == '.md':
            node_type = NodeType.ARTIFACT
        else:
            node_type = NodeType.FILE
        
        # Read file content
        try:
            content = filepath.read_text(encoding='utf-8', errors='replace')
        except Exception:
            content = ""
        
        # Calculate hashes
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        semantic_hash = self._compute_semantic_hash(content, language)
        
        # Count lines
        line_count = content.count('\n') + 1 if content else 0
        
        # Create relative path ID
        try:
            rel_path = str(filepath.relative_to(self._root_path))
        except ValueError:
            rel_path = str(filepath)
        
        return NodeInfo(
            id=rel_path,
            type=node_type,
            location=rel_path,
            content_hash=content_hash,
            semantic_hash=semantic_hash,
            line_count=line_count,
            language=language,
            metadata={
                'extension': ext,
                'size_bytes': filepath.stat().st_size if filepath.exists() else 0,
            }
        )
    
    def _compute_semantic_hash(self, content: str, language: str) -> str:
        """
        Compute semantic hash for content.
        
        Ignores whitespace, comments, and formatting.
        """
        # Remove comments based on language
        if language == 'python':
            # Remove Python comments and docstrings
            content = re.sub(r'#.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'""".*?"""', '', content, flags=re.DOTALL)
            content = re.sub(r"'''.*?'''", '', content, flags=re.DOTALL)
        elif language in ('javascript', 'typescript'):
            # Remove JS/TS comments
            content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
            content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content)
        content = content.strip()
        
        return hashlib.sha256(content.encode()).hexdigest()[:32]
    
    def _analyze_dependencies(self) -> None:
        """Analyze import/dependency relationships."""
        for node_id, node in self._nodes.items():
            if node.type == NodeType.FILE and node.language:
                self._extract_imports(node)
    
    def _extract_imports(self, node: NodeInfo) -> None:
        """Extract import statements from a node."""
        filepath = self._root_path / node.location
        patterns = self.IMPORT_PATTERNS.get(node.language, [])
        
        try:
            content = filepath.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return
        
        for pattern, import_type in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                imported = match.group(1)
                
                # Resolve to actual file path
                resolved = self._resolve_import(imported, node.location)
                if resolved:
                    self._import_graph[node.id].add(resolved)
    
    def _resolve_import(self, import_name: str, from_file: str) -> Optional[str]:
        """Resolve an import to a file path."""
        # Convert module name to file path
        parts = import_name.replace('.', '/').split('/')
        
        # Try various resolutions
        candidates = []
        
        # Direct file match
        for ext in self.SOURCE_EXTENSIONS:
            candidates.append('/'.join(parts) + ext)
        
        # Package index
        candidates.append('/'.join(parts) + '/__init__.py')
        candidates.append('/'.join(parts) + '/index.js')
        candidates.append('/'.join(parts) + '/index.ts')
        
        # Check each candidate
        for candidate in candidates:
            if candidate in self._nodes:
                return candidate
        
        return None
    
    def _calculate_trust_scores(self) -> None:
        """Calculate trust scores for all nodes."""
        for node_id, node in self._nodes.items():
            score = 0.5  # Base trust
            
            # Apply modifiers
            if 'test' in node_id.lower():
                score += self.TRUST_MODIFIERS['test_file']
            
            if node.type == NodeType.CONFIG:
                score += self.TRUST_MODIFIERS['config_file']
            
            # Check for core module patterns
            for pattern in self.CORE_PATTERNS:
                if re.search(pattern, node_id):
                    score += self.TRUST_MODIFIERS['core_module']
                    break
            
            # Generated files
            if 'generated' in node_id.lower() or node_id.startswith('_'):
                score += self.TRUST_MODIFIERS['generated']
            
            # Documentation
            if node.language == 'markdown':
                score += self.TRUST_MODIFIERS['documentation']
            
            # Usage factor (files with more imports are more trusted)
            import_count = sum(
                1 for imports in self._import_graph.values()
                if node_id in imports
            )
            if import_count > 5:
                score += min(0.1, import_count * 0.01)
            
            # Clamp to [0.0, 1.0]
            node.trust_score = max(0.0, min(1.0, score))
    
    def _build_edges(self) -> None:
        """Build edges from import graph."""
        for from_id, to_ids in self._import_graph.items():
            for to_id in to_ids:
                edge = EdgeInfo(
                    from_id=from_id,
                    to_id=to_id,
                    relation=EdgeRelation.IMPORTS,
                    weight=1.0,
                )
                self._edges.append(edge)
    
    def _generate_output(self) -> Dict[str, Any]:
        """Generate the output context graph dictionary."""
        # Calculate trust distribution
        trust_distribution = {
            "TIER_1_TRUSTED": 0,
            "TIER_2_RELIABLE": 0,
            "TIER_3_UNCERTAIN": 0,
            "TIER_4_UNTRUSTED": 0,
        }
        
        for node in self._nodes.values():
            if node.trust_score >= 0.8:
                trust_distribution["TIER_1_TRUSTED"] += 1
            elif node.trust_score >= 0.6:
                trust_distribution["TIER_2_RELIABLE"] += 1
            elif node.trust_score >= 0.4:
                trust_distribution["TIER_3_UNCERTAIN"] += 1
            else:
                trust_distribution["TIER_4_UNTRUSTED"] += 1
        
        # Calculate average trust
        avg_trust = (
            sum(n.trust_score for n in self._nodes.values()) / len(self._nodes)
            if self._nodes else 0.0
        )
        
        # Build nodes array
        nodes = [
            {
                "id": node.id,
                "type": node.type.value,
                "location": node.location,
                "trust_score": round(node.trust_score, 3),
                "content_hash": node.content_hash,
                "semantic_hash": node.semantic_hash,
                "last_modified": datetime.now(timezone.utc).isoformat(),
                "usage_count": 0,
                "success_rate": 1.0,
                "metadata": node.metadata,
            }
            for node in self._nodes.values()
        ]
        
        # Build edges array
        edges = [
            {
                "from": edge.from_id,
                "to": edge.to_id,
                "relation": edge.relation.value,
                "weight": edge.weight,
            }
            for edge in self._edges
        ]
        
        return {
            "version": "1.0.0",
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "avg_trust_score": round(avg_trust, 3),
                "stale_nodes": [],
                "trust_distribution": trust_distribution,
                "protocol_version": "5.1.0",
                "root_path": str(self._root_path),
            }
        }
    
    def save(self, graph: Dict[str, Any], output_path: str) -> None:
        """Save context graph to file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(graph, f, indent=2)
        
        logger.info(f"[ContextGraphBuilder] Saved context graph to {output_path}")


def build_context_graph(
    root_path: str = ".",
    output_path: str = ".ai/context_graph.json",
    exclude_dirs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to build and save context graph.
    
    Args:
        root_path: Root directory to analyze
        output_path: Path to save context_graph.json
        exclude_dirs: Directories to exclude
        
    Returns:
        The generated context graph
    """
    builder = ContextGraphBuilder(
        root_path=root_path,
        exclude_dirs=exclude_dirs,
    )
    graph = builder.build()
    builder.save(graph, output_path)
    return graph


if __name__ == "__main__":
    import sys
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Build from current directory or specified path
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    output = sys.argv[2] if len(sys.argv) > 2 else ".ai/context_graph.json"
    
    build_context_graph(root, output)
