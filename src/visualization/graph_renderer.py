"""
Graph Renderer for TITAN FUSE Protocol.

ITEM-CONFLICT-L: Provides ASCII and GraphViz rendering for DAGs
with graceful fallback when GraphViz is unavailable.

Author: TITAN FUSE Team
Version: 3.4.0
"""

from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from enum import Enum
import subprocess
import shutil
import logging
from pathlib import Path


class RenderMode(Enum):
    """Graph rendering modes."""
    ASCII = "ascii_only"
    FULL = "full"


@dataclass
class GraphNode:
    """A node in the graph."""
    id: str
    label: str
    node_type: str = "default"
    status: str = "pending"
    dependencies: List[str] = None
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


@dataclass
class RenderConfig:
    """Graph rendering configuration."""
    mode: RenderMode
    graphviz_path: Optional[str]
    
    def to_dict(self) -> Dict:
        return {
            "mode": self.mode.value,
            "graphviz_path": self.graphviz_path
        }


class GraphRenderer:
    """
    Render graphs with ASCII or GraphViz output.
    
    ITEM-CONFLICT-L: GraphViz optional dependency handling.
    
    Provides:
    - ASCII rendering (always available)
    - GraphViz rendering (optional, with fallback)
    - Automatic mode selection based on environment
    
    Usage:
        config = {
            "mode": "ascii_only",
            "graphviz_path": None
        }
        
        renderer = GraphRenderer(config)
        
        # Render graph
        output = renderer.render(graph, mode="ascii_only")
        
        # Check capabilities
        if renderer.is_graphviz_available():
            output = renderer.render(graph, mode="full")
    """
    
    DEFAULT_CONFIG = RenderConfig(
        mode=RenderMode.ASCII,
        graphviz_path=None
    )
    
    def __init__(self, config: Dict = None):
        """
        Initialize graph renderer.
        
        Args:
            config: Rendering configuration
        """
        if config is None:
            config = {}
        
        mode_str = config.get("mode", "ascii_only")
        try:
            mode = RenderMode(mode_str)
        except ValueError:
            mode = RenderMode.ASCII
        
        self._config = RenderConfig(
            mode=mode,
            graphviz_path=config.get("graphviz_path")
        )
        
        self._logger = logging.getLogger(__name__)
        self._graphviz_available = None  # Lazy check
    
    def render(self, graph: Dict, mode: str = None) -> str:
        """
        Render a graph.
        
        Args:
            graph: Graph data with nodes and edges
            mode: Override render mode ("ascii_only" or "full")
            
        Returns:
            Rendered graph as string
        """
        render_mode = self._get_render_mode(mode)
        
        if render_mode == RenderMode.FULL:
            if self.is_graphviz_available():
                return self.render_graphviz(graph)
            else:
                self._logger.warning(
                    "[warn: graphviz_not_available] Using ASCII fallback"
                )
                return self.render_ascii(graph)
        
        return self.render_ascii(graph)
    
    def _get_render_mode(self, mode: str = None) -> RenderMode:
        """Get render mode from parameter or config."""
        if mode:
            try:
                return RenderMode(mode)
            except ValueError:
                pass
        return self._config.mode
    
    def render_ascii(self, graph: Dict) -> str:
        """
        Render graph as ASCII art.
        
        Args:
            graph: Graph data with nodes and edges
            
        Returns:
            ASCII representation of graph
        """
        nodes = self._parse_nodes(graph)
        edges = self._parse_edges(graph)
        
        lines = []
        lines.append("┌─────────────────────────────────┐")
        lines.append("│         DAG Visualization       │")
        lines.append("└─────────────────────────────────┘")
        lines.append("")
        
        # Group nodes by level (topological)
        levels = self._compute_levels(nodes, edges)
        
        for level, level_nodes in sorted(levels.items()):
            lines.append(f"Level {level}:")
            for node_id in level_nodes:
                node = nodes.get(node_id)
                if node:
                    status_icon = self._get_status_icon(node.get("status", "pending"))
                    node_type = node.get("node_type", "default")
                    label = node.get("label", node_id)
                    lines.append(f"  {status_icon} [{node_type}] {label} ({node_id})")
                    
                    # Show dependencies
                    deps = node.get("dependencies", [])
                    if deps:
                        lines.append(f"      ↑ depends on: {', '.join(deps)}")
            lines.append("")
        
        # Summary
        total_nodes = len(nodes)
        total_edges = sum(len(deps) for deps in edges.values())
        lines.append(f"Total: {total_nodes} nodes, {total_edges} edges")
        
        return "\n".join(lines)
    
    def _get_status_icon(self, status: str) -> str:
        """Get icon for node status."""
        icons = {
            "pending": "○",
            "running": "◐",
            "completed": "●",
            "failed": "✗",
            "skipped": "⊘"
        }
        return icons.get(status, "○")
    
    def render_graphviz(self, graph: Dict) -> str:
        """
        Render graph using GraphViz DOT.
        
        Args:
            graph: Graph data with nodes and edges
            
        Returns:
            DOT format representation
        """
        nodes = self._parse_nodes(graph)
        edges = self._parse_edges(graph)
        
        lines = ["digraph G {"]
        lines.append("    rankdir=TB;")
        lines.append("    node [shape=box, style=rounded];")
        lines.append("")
        
        # Define nodes
        lines.append("    // Nodes")
        for node_id, node in nodes.items():
            label = node.get("label", node_id)
            node_type = node.get("node_type", "default")
            status = node.get("status", "pending")
            
            # Style based on status
            style = self._get_graphviz_style(status)
            color = self._get_graphviz_color(status)
            
            lines.append(
                f'    "{node_id}" [label="{label}\\n({node_type})", '
                f'style="{style}", fillcolor="{color}"];'
            )
        
        lines.append("")
        lines.append("    // Edges")
        
        # Define edges
        for node_id, deps in edges.items():
            for dep in deps:
                lines.append(f'    "{dep}" -> "{node_id}";')
        
        lines.append("}")
        
        return "\n".join(lines)
    
    def _get_graphviz_style(self, status: str) -> str:
        """Get GraphViz style for status."""
        styles = {
            "pending": "rounded",
            "running": "rounded,filled",
            "completed": "rounded,filled",
            "failed": "rounded,filled",
            "skipped": "rounded,dashed"
        }
        return styles.get(status, "rounded")
    
    def _get_graphviz_color(self, status: str) -> str:
        """Get GraphViz color for status."""
        colors = {
            "pending": "white",
            "running": "yellow",
            "completed": "lightgreen",
            "failed": "lightcoral",
            "skipped": "lightgray"
        }
        return colors.get(status, "white")
    
    def _parse_nodes(self, graph: Dict) -> Dict:
        """Parse nodes from graph data."""
        nodes = {}
        
        # Handle different graph formats
        if "nodes" in graph:
            for node in graph["nodes"]:
                if isinstance(node, dict):
                    nodes[node["id"]] = node
                else:
                    nodes[str(node)] = {"id": str(node)}
        elif "vertices" in graph:
            for node in graph["vertices"]:
                if isinstance(node, dict):
                    nodes[node["id"]] = node
                else:
                    nodes[str(node)] = {"id": str(node)}
        
        return nodes
    
    def _parse_edges(self, graph: Dict) -> Dict[str, List[str]]:
        """Parse edges from graph data."""
        edges = {}
        
        # Handle different graph formats
        if "edges" in graph:
            for edge in graph["edges"]:
                if isinstance(edge, dict):
                    source = edge.get("source") or edge.get("from")
                    target = edge.get("target") or edge.get("to")
                    if target not in edges:
                        edges[target] = []
                    edges[target].append(source)
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    source, target = edge[0], edge[1]
                    if target not in edges:
                        edges[target] = []
                    edges[target].append(source)
        elif "dependencies" in graph:
            for node_id, deps in graph["dependencies"].items():
                edges[node_id] = list(deps)
        
        return edges
    
    def _compute_levels(self, nodes: Dict, edges: Dict) -> Dict[int, List[str]]:
        """Compute topological levels for nodes."""
        levels: Dict[int, List[str]] = {}
        node_levels: Dict[str, int] = {}
        
        # Find nodes with no dependencies (level 0)
        all_nodes = set(nodes.keys())
        for node_id in all_nodes:
            deps = edges.get(node_id, [])
            if not deps:
                node_levels[node_id] = 0
        
        # BFS to assign levels
        remaining = all_nodes - set(node_levels.keys())
        max_iterations = len(all_nodes) + 10
        iteration = 0
        
        while remaining and iteration < max_iterations:
            iteration += 1
            changed = False
            
            for node_id in list(remaining):
                deps = edges.get(node_id, [])
                if all(dep in node_levels for dep in deps):
                    if deps:
                        node_levels[node_id] = max(node_levels[d] for d in deps) + 1
                    else:
                        node_levels[node_id] = 0
                    remaining.remove(node_id)
                    changed = True
            
            if not changed:
                # Cycle detected or missing nodes
                for node_id in remaining:
                    node_levels[node_id] = -1  # Unknown level
                break
        
        # Group by level
        for node_id, level in node_levels.items():
            if level not in levels:
                levels[level] = []
            levels[level].append(node_id)
        
        return levels
    
    def is_graphviz_available(self) -> bool:
        """
        Check if GraphViz is available.
        
        Returns:
            True if dot command is available
        """
        if self._graphviz_available is not None:
            return self._graphviz_available
        
        # Check configured path first
        if self._config.graphviz_path:
            path = Path(self._config.graphviz_path)
            if path.exists():
                self._graphviz_available = True
                return True
        
        # Check system PATH
        dot_path = shutil.which("dot")
        if dot_path:
            self._graphviz_available = True
            return True
        
        self._graphviz_available = False
        self._logger.debug("GraphViz not available")
        return False
    
    def render_to_file(self, graph: Dict, output_path: Path, 
                       format: str = "svg", mode: str = None) -> bool:
        """
        Render graph to file.
        
        Args:
            graph: Graph data
            output_path: Output file path
            format: Output format (svg, png, pdf)
            mode: Render mode override
            
        Returns:
            True if successful
        """
        render_mode = self._get_render_mode(mode)
        
        if render_mode == RenderMode.FULL and self.is_graphviz_available():
            dot_content = self.render_graphviz(graph)
            return self._render_dot_to_file(dot_content, output_path, format)
        else:
            # ASCII output
            ascii_content = self.render_ascii(graph)
            output_path.write_text(ascii_content)
            return True
    
    def _render_dot_to_file(
        self, dot_content: str, output_path: Path, format: str
    ) -> bool:
        """Render DOT content to file using GraphViz."""
        try:
            process = subprocess.run(
                ["dot", f"-T{format}", "-o", str(output_path)],
                input=dot_content,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if process.returncode == 0:
                self._logger.info(f"Graph rendered to {output_path}")
                return True
            else:
                self._logger.error(f"GraphViz error: {process.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self._logger.error("GraphViz timeout")
            return False
        except Exception as e:
            self._logger.error(f"GraphViz render error: {e}")
            return False
    
    def get_config(self) -> RenderConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, config: Dict) -> None:
        """Update configuration."""
        if "mode" in config:
            try:
                self._config.mode = RenderMode(config["mode"])
            except ValueError:
                pass
        if "graphviz_path" in config:
            self._config.graphviz_path = config["graphviz_path"]
            self._graphviz_available = None  # Re-check


def create_graph_renderer(config: Dict = None) -> GraphRenderer:
    """
    Factory function to create a GraphRenderer.
    
    Args:
        config: Configuration dictionary
        
    Returns:
        GraphRenderer instance
    """
    return GraphRenderer(config)
